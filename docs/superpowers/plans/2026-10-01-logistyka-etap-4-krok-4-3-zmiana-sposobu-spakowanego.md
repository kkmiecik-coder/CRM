# Zmiana sposobu dostawy na spakowanym zamówieniu (krok 4.3, dodatek) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zmiana sposobu dostawy na zamówieniu w całości spakowanym nie kończy się błędem ani cichym przepakowaniem. Panel Logistyki pyta logistyka, czy cofnąć zamówienie do pakowania. Backend wymaga tej decyzji i ją egzekwuje.

**Architecture:** Serwis `delivery.ustaw_sposob_dostawy` dostaje parametr `przepakowanie` (`True` / `False` / `None`). Dla zamówienia w całości spakowanego `None` daje odmowę z kodem `wymaga_decyzji_przepakowania` i listą opcji. Endpoint panelu przekazuje pole JSON `przepakowanie` i zwraca odmowy w istniejącej liście `bledy`, z polami `kod` i `opcje`. Stary front pokaże je jako zwykłą odmowę. Front zbiera decyzję w oknie (`<dialog>` w stylu zakładki) PRZED wysłaniem, więc w hurcie jedno okno obejmuje całą partię. Drugie okno pyta o zamówienia, dla których przepakowanie jest obowiązkowe. Jeśli front miał nieaktualne dane, a serwer odpowie `wymaga_decyzji_przepakowania`, okno pokazuje się po odpowiedzi.

**Tech Stack:** Flask, SQLAlchemy < 2.0, Python 3.9 (produkcja), MySQL 8.4 REPEATABLE READ (produkcja), SQLite (testy), czysty JS w `logistics.js`, natywny `<dialog>`.

**Spec:** `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md`, sekcja **8.7** (oraz 4.5, 8.4, 8.5).

## Global Constraints

- Produkcja chodzi na Pythonie 3.9: bez `X | Y` w adnotacjach i bez `match`.
- SQLAlchemy < 2.0.
- Komentarze w kodzie po polsku. Teksty UI po polsku, „Base.” zamiast BaseLinker/BL.
- Repo jest publiczne: bez sekretów, adresów IP drukarek i uwag o bezpieczeństwie. Spec i plan commitujemy przez `git add -f`.
- Testy WYŁĄCZNIE z katalogu worktree zadania: `docker compose -p <projekt> run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`. Nigdy `docker compose exec`. Najwyżej 2 pełne pakiety naraz.
- Commity: Conventional Commits po polsku, temat bez polskich znaków, stopka `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Bez pusha i bez merge do `main`.
- `tools/print_agent` bez zmian.
- Kolejność blokad zapisów panelu: `_zapis_pod_blokada()` (commit, potem blokada tras) → wiersze zamówień `FOR UPDATE` rosnąco po id → dopiero potem zwykły odczyt pozycji (migawka powstaje po blokadach) → zapisy. Pozycji panel NIE blokuje przed zamówieniem: stanowiska biorą pozycję przed zamówieniem, więc to dałoby 1213 z „ZAKOŃCZ” (CLAUDE.md, „Deklaracje paczek”).
- Między `_zapis_pod_blokada()` a blokadą zamówień nie może być żadnego zwykłego odczytu, także atrybutów ORM wygaszonych przez commit (np. `current_user.id`). `user_id` liczymy PRZED `_zapis_pod_blokada()`.
- „W całości spakowane” = `delivery.wszystkie_spakowane(order)` (spakowane lub dalej). Załadowane i dostarczone odpadają wcześniej istniejącą blokadą.
- Częściowo spakowane działa jak dotąd: zmiana na kuriera z transportu albo odbioru sama przepakowuje spakowane pozycje, „Nie ustawiono” daje błąd (decyzja Konrada 1.10).

## Decyzje Konrada (1.10.2026, w tej sesji)

1. Okno przy KAŻDEJ zmianie sposobu na zamówieniu w całości spakowanym (przekazane przez centralę).
2. Hurt: gdy logistyk wybierze „Zmień bez przepakowania”, a część zamówień wymaga przepakowania, decyduje o nich w drugim oknie: „Cofnij je do pakowania” albo „Pomiń je”.
3. Okno tylko dla zamówień w CAŁOŚCI spakowanych. Częściowo spakowane bez zmian.
4. Baner ze sposobem: „Logistyka: zmiana sposobu dostawy na <sposób>” albo „Logistyka: sposób dostawy do ustalenia”. Kolejna zmiana przed spakowaniem przepisuje baner. Powód z Weryfikacji ma pierwszeństwo.

## Odstępstwa od propozycji centrali (rozstrzygnięcia sesji 4.3)

- Zamiast 409 dla całego żądania odmowa przychodzi per zamówienie w istniejącej liście `bledy` (`kod`, `opcje`). Endpoint obsługuje już pojedynczą zmianę i hurt (do 500 id, kilka grup sposobów w podpowiedziach), a odmowy per zamówienie już w nim są. Zamówienia niespakowane z tej samej partii zmieniają się od razu. Front i tak pyta przed wysłaniem.
- Przy „Cofnij do pakowania” z panelu panel nie bierze blokady deklaracji paczek. Wiersz zamówienia `FOR UPDATE` serializuje go z Weryfikacją i deklaracją, bo obie biorą zamówienie przed paczkami.

## Tory realizacji

Task 1 (backend) i Task 2 (front) idą równolegle w osobnych worktree. Front opiera się wyłącznie na kontrakcie niżej, a scalamy cherry-pickiem. Task 3 rusza po obu.

## Kontrakt (endpoint panelu)

`POST /production/api/logistics/orders/delivery-method`, ciało: `{"order_ids": [...], "sposob": "...", "przepakowanie": true|false}`. Pole `przepakowanie` jest opcjonalne. Każda inna wartość niż `true`, `false`, `null` albo brak pola → 422 „Pole przepakowanie musi mieć wartość true albo false.”

| Zamówienie | `przepakowanie` | Skutek |
|---|---|---|
| niespakowane albo częściowo spakowane | dowolne | jak dotąd, parametr pomijany |
| w całości spakowane | brak / `null` | bez zmian; `bledy` += `{order_id, komunikat, kod: "wymaga_decyzji_przepakowania", opcje}` |
| w całości spakowane, przepakowanie obowiązkowe | `false` | bez zmian; `bledy` += `{order_id, komunikat, kod: "wymaga_przepakowania"}` |
| w całości spakowane, przepakowanie dobrowolne | `false` | zmiana bez przepakowania (jak dotąd) |
| w całości spakowane | `true` | cofnięcie do pakowania + nowy sposób; id w `przepakowanie` odpowiedzi |

Przepakowanie jest obowiązkowe przy zmianie na „Nie ustawiono” (`brak`) albo na kuriera z transportu własnego lub odbioru. `opcje` = `["przepakuj"]` (obowiązkowe) albo `["przepakuj", "bez_przepakowania"]`. Istniejące blokady (wydane, anulowane, załadowane/dostarczone, przesyłka, trasa wykonana, trasa zatwierdzona przy zdjęciu z trasy) wygrywają z oknem i zostają odmowami bez `kod`.

Komunikaty (dosłownie):
- `wymaga_decyzji_przepakowania`: `Zamówienie {nr} jest w całości spakowane — wybierz, czy cofnąć je do pakowania (odśwież stronę, jeśli nie widzisz okna).`
- `wymaga_przepakowania`: `Zamówienie {nr}: zmiana na „{etykieta}” wymaga cofnięcia do pakowania — nie zmieniono.` Tu `etykieta` to `sposoby.etykieta(nowy)`, a dla `brak` to `Nie ustawiono`.

## Review Focus

1. Karta otwarta w czasie wdrożenia (stary JS bez okna) zmienia sposób spakowanego zamówienia. Oczekiwane: zamówienie się nie zmienia, a logistyk widzi odmowę z komunikatem, bez cichego przepakowania. Test: Task 1, `test_endpoint_bez_decyzji_nie_zmienia_i_zwraca_kod`.
2. Wiersz w przeglądarce jest nieaktualny: zamówienie spakowało się po wczytaniu listy. Oczekiwane: serwer odpowiada `wymaga_decyzji_przepakowania`, a front pokazuje okno dla tych zamówień i wysyła je ponownie z decyzją. Test: Task 2, statyczny test obsługi kodu w `logistics.js`.
3. Baner: powód z Weryfikacji nie jest nadpisywany przez „Cofnij do pakowania” z panelu. Baner „Logistyka: …” przepisuje się przy kolejnej zmianie i znika po spakowaniu. Test: Task 1, `test_baner_*`.
4. „Nie ustawiono” + „Cofnij do pakowania”: tablet pakowania dostaje 409 `delivery_method_not_set` do czasu wyboru sposobu, a baner „do ustalenia” zmienia się na sposób po wyborze. Test: Task 1, `test_brak_z_przepakowaniem_*`.
5. Hurt z „Anuluj”: nic nie idzie do serwera, także dla zamówień niespakowanych. Test: Task 2, statyczny test ścieżki anulowania.

---

### Task 1: Backend — decyzja o przepakowaniu w serwisie i endpoincie

**Files:**
- Modify: `modules/production/logistics/sposoby.py` (stałe i pomocniki banera)
- Modify: `modules/production/logistics/services/delivery.py` (`ustaw_sposob_dostawy`, `_cofnij_sposob`, nowy `_odswiez_baner_logistyki`)
- Modify: `modules/production/logistics/routers/panel_api.py` (`delivery_method`)
- Test: `tests/test_logistyka_zmiana_spakowanego.py` (nowy)
- Test: dostosowanie istniejących testów, które zmieniają sposób zamówienia w całości spakowanego (reguła w kroku 6)

**Interfaces:**
- Produces: `sposoby.PREFIKS_BANERA_LOGISTYKI = u'Logistyka: '`, `sposoby.baner_logistyki(sposob) -> str`, `sposoby.baner_systemowy(tekst) -> bool`, `delivery.przepakowanie_obowiazkowe(stary, nowy) -> bool` (`nowy=None` oznacza „Nie ustawiono”), `delivery.ustaw_sposob_dostawy(order, sposob, user_id=None, teraz=None, przepakowanie=None)`. `LogistykaBlad.dane` niesie `{'kod': ..., 'opcje': [...]}`.
- Consumes: istniejące `delivery.wszystkie_spakowane`, `aktywne_produkty`, `_przystanek_do_zmiany`, `zapisz_log`, `weryfikacja.uniewaznij_etapy`.

- [ ] **Step 1: Pomocniki banera w `sposoby.py`** (pod `PRZEPAKUJ_NA_KURIERA`)

```python
# Baner po „Cofnij do pakowania” z panelu Logistyki (spec 8.7). Prefiks odróżnia baner panelu, który kolejna
# zmiana sposobu przepisuje, od powodu z Weryfikacji („Weryfikacja: …”), którego system nie nadpisuje.
PREFIKS_BANERA_LOGISTYKI = u'Logistyka: '


def baner_logistyki(sposob):
    """Tekst banera przepakowania z panelu; `sposob` None = „Nie ustawiono”."""
    s = normalizuj(sposob)
    if s is None:
        return PREFIKS_BANERA_LOGISTYKI + u'sposób dostawy do ustalenia'
    return PREFIKS_BANERA_LOGISTYKI + u'zmiana sposobu dostawy na ' + _ETYKIETA[s]


def baner_systemowy(tekst):
    """Baner, który system może nadpisać: brak, „Przepakuj na kuriera” albo baner panelu (spec 8.7)."""
    return not tekst or tekst == PRZEPAKUJ_NA_KURIERA or tekst.startswith(PREFIKS_BANERA_LOGISTYKI)
```

(`_ETYKIETA` jest zdefiniowane niżej w pliku. Funkcje wołane w czasie działania widzą je bez problemu.)

- [ ] **Step 2: Testy serwisu (failing)** w nowym `tests/test_logistyka_zmiana_spakowanego.py`

```python
# -*- coding: utf-8 -*-
"""Krok 4.3, spec 8.7: zmiana sposobu dostawy na zamówieniu w całości spakowanym wymaga decyzji o przepakowaniu."""
import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import delivery as d
from modules.production.models import ProductionPackage, get_local_now
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401

T0 = get_local_now().replace(microsecond=0)

OBOWIAZKOWE = [(s.TRANSPORT, s.KURIER), (s.ODBIOR, s.KURIER),
               (s.KURIER, s.BRAK), (s.TRANSPORT, s.BRAK), (s.ODBIOR, s.BRAK)]
DOBROWOLNE = [(s.KURIER, s.TRANSPORT), (s.KURIER, s.ODBIOR), (s.TRANSPORT, s.ODBIOR), (s.ODBIOR, s.TRANSPORT)]


def _akcje():
    return [l.action for l in LogisticsLog.query.order_by(LogisticsLog.id)]


@pytest.mark.parametrize('stary,nowy', OBOWIAZKOWE + DOBROWOLNE)
def test_bez_decyzji_wymaga_decyzji_i_nic_nie_zmienia(app, stary, nowy):
    with app.app_context():
        order = zamowienie(sposob=stary, statusy=('spakowane', 'zweryfikowane'))
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, nowy, teraz=T0)
        assert e.value.dane['kod'] == 'wymaga_decyzji_przepakowania'
        oczekiwane = ['przepakuj'] if (stary, nowy) in OBOWIAZKOWE else ['przepakuj', 'bez_przepakowania']
        assert e.value.dane['opcje'] == oczekiwane
        assert s.normalizuj(order.override_delivery_method) == stary
        assert [p.current_status for p in order.products] == ['spakowane', 'zweryfikowane']
        assert _akcje() == []


@pytest.mark.parametrize('stary,nowy', OBOWIAZKOWE)
def test_bez_przepakowania_przy_obowiazkowym_odmawia(app, stary, nowy):
    with app.app_context():
        order = zamowienie(sposob=stary, statusy=('spakowane',))
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, nowy, teraz=T0, przepakowanie=False)
        assert e.value.dane['kod'] == 'wymaga_przepakowania'
        assert s.normalizuj(order.override_delivery_method) == stary
        assert order.products[0].current_status == 'spakowane'


@pytest.mark.parametrize('stary,nowy', DOBROWOLNE)
def test_bez_przepakowania_przy_dobrowolnym_zmienia_jak_dotad(app, stary, nowy):
    with app.app_context():
        order = zamowienie(sposob=stary, statusy=('spakowane',))
        wynik = d.ustaw_sposob_dostawy(order, nowy, teraz=T0, przepakowanie=False)
        assert wynik['zmieniono'] is True and wynik['przepakowanie'] is False
        assert order.override_delivery_method == nowy
        assert order.products[0].current_status == 'spakowane'
        assert order.bl_status_pending_id == s.STATUS_PO_SPAKOWANIU[nowy]
        assert order.repack_required is False


@pytest.mark.parametrize('stary,nowy', OBOWIAZKOWE + DOBROWOLNE)
def test_z_przepakowaniem_cofa_do_pakowania(app, stary, nowy):
    with app.app_context():
        order = zamowienie(sposob=stary, statusy=('spakowane', 'zweryfikowane'))
        order.verified_at = T0
        db.session.add(ProductionPackage(order_id=order.id, seq=1, kind='paczka', declared_at=T0))
        db.session.commit()
        wynik = d.ustaw_sposob_dostawy(order, nowy, user_id=3, teraz=T0, przepakowanie=True)
        db.session.commit()
        assert wynik['przepakowanie'] is True
        assert all(p.current_status == 'czeka_na_pakowanie' for p in order.products)
        assert all(p.packaging_completed_at is None for p in order.products)
        assert order.repack_required is True
        assert order.verified_at is None
        assert all(p.voided_at is not None for p in ProductionPackage.query.filter_by(order_id=order.id))
        assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
        if nowy == s.BRAK:
            assert order.override_delivery_method is None
            assert order.repack_reason == s.baner_logistyki(None)
        elif nowy == s.KURIER:
            assert order.repack_reason == s.PRZEPAKUJ_NA_KURIERA
        else:
            assert order.override_delivery_method == nowy
            assert order.repack_reason == s.baner_logistyki(nowy)
        assert 'przepakowanie' in _akcje()


def test_czesciowo_spakowane_jak_dotad_bez_decyzji(app):
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane', 'czeka_na_pakowanie'))
        wynik = d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0)          # bez parametru: auto, jak dotąd
        assert wynik['przepakowanie'] is True
        order2 = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane', 'czeka_na_pakowanie'))
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order2, s.BRAK, teraz=T0, przepakowanie=True)
        assert e.value.dane.get('kod') is None                             # dawny błąd „nie da się cofnąć”


def test_baner_weryfikacji_nie_jest_nadpisywany(app):
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
        order.repack_required = True
        order.repack_reason = u'Weryfikacja: Uszkodzenie: pęknięty blat'
        db.session.commit()
        d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0, przepakowanie=True)
        assert order.repack_reason == u'Weryfikacja: Uszkodzenie: pęknięty blat'


def test_baner_logistyki_przepisuje_sie_przy_kolejnej_zmianie(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0, przepakowanie=True)
        assert order.repack_reason == s.baner_logistyki(s.ODBIOR)
        d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T0)    # pozycje już w pakowaniu → zwykła zmiana
        assert order.repack_required is True
        assert order.repack_reason == s.baner_logistyki(s.TRANSPORT)


def test_brak_z_przepakowaniem_potem_wybor_sposobu(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        d.ustaw_sposob_dostawy(order, s.BRAK, teraz=T0, przepakowanie=True)
        assert order.override_delivery_method is None
        assert order.repack_reason == s.baner_logistyki(None)
        d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0)
        assert order.override_delivery_method == s.ODBIOR
        assert order.repack_reason == s.baner_logistyki(s.ODBIOR)


def test_blokady_wygrywaja_z_decyzja(app):
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('dostarczone',))
        order.handed_over_at = T0
        db.session.commit()
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0, przepakowanie=True)
        assert e.value.dane.get('kod') is None
```

Uruchom: `docker compose -p logistyka4 run --rm --no-deps app pytest tests/test_logistyka_zmiana_spakowanego.py -q -p no:cacheprovider`. Oczekiwane: FAIL (brak parametru `przepakowanie`, brak `baner_logistyki`).

(Jeśli fabryka `zamowienie` albo model paczki wymaga innych pól, dopasuj przygotowanie danych, a asercje zostaw. Wzorce paczek są w `tests/test_weryfikacja_regula.py`.)

- [ ] **Step 3: Serwis** w `delivery.py`

3a. Pomocnik obok `_zdejmij_baner_przepakowania_na_kuriera`:

```python
def przepakowanie_obowiazkowe(stary, nowy):
    """Spec 8.7: bez przepakowania nie wolno przy „Nie ustawiono” (nowy None) albo przy zmianie na kuriera
    z transportu własnego lub odbioru (paczki pod inny sposób, kolejny wybór nie wiedziałby, pod co pakowano)."""
    return nowy is None or (nowy == sposoby.KURIER and stary in (sposoby.TRANSPORT, sposoby.ODBIOR))


def _odswiez_baner_logistyki(order, nowy):
    """Baner „Logistyka: …” (spec 8.7) idzie za bieżącym sposobem, dopóki pozycje nie zostaną spakowane."""
    if order.repack_required and (order.repack_reason or '').startswith(sposoby.PREFIKS_BANERA_LOGISTYKI):
        order.repack_reason = sposoby.baner_logistyki(nowy)
```

3b. `ustaw_sposob_dostawy(order, sposob, user_id=None, teraz=None, przepakowanie=None)`. Docstring opisuje parametr: `None` = brak decyzji, `True` = cofnij do pakowania, `False` = bez przepakowania. Parametr działa wyłącznie dla zamówienia w całości spakowanego (spec 8.7). Zmiany:

- Bez zmian: walidacja, wydane, anulowane, ten sam sposób, załadowane/dostarczone, przesyłka i `przystanek = _przystanek_do_zmiany(...)`.
- Zaraz po `_przystanek_do_zmiany` i PRZED gałęzią `if cofniecie:` dodaj:

```python
    w_calosci = wszystkie_spakowane(order)
    decyzja = None
    if w_calosci:
        # Spec 8.7: każda zmiana sposobu na zamówieniu w całości spakowanym wymaga decyzji logistyka.
        obowiazkowe = przepakowanie_obowiazkowe(stary, nowy)
        if przepakowanie is None:
            raise LogistykaBlad(
                u'Zamówienie {} jest w całości spakowane — wybierz, czy cofnąć je do pakowania (odśwież stronę, '
                u'jeśli nie widzisz okna).'.format(order.internal_order_number),
                dane={'kod': 'wymaga_decyzji_przepakowania',
                      'opcje': ['przepakuj'] if obowiazkowe else ['przepakuj', 'bez_przepakowania']})
        if przepakowanie is False and obowiazkowe:
            raise LogistykaBlad(u'Zamówienie {}: zmiana na „{}” wymaga cofnięcia do pakowania — nie zmieniono.'.format(
                order.internal_order_number, sposoby.etykieta(nowy)), dane={'kod': 'wymaga_przepakowania'})
        decyzja = bool(przepakowanie)
```

(`sposoby.etykieta(None)` zwraca „Nie ustawiono”.)

- Gałąź `if cofniecie:`. Dawny błąd „nie da się cofnąć” zostaje TYLKO dla zamówień częściowo spakowanych: `if not w_calosci and any(...STATUSY_PO_SPAKOWANIU...)`. Dla `w_calosci` (wtedy `decyzja is True`, bo `False` odpadło wyżej) najpierw cofnij do pakowania, potem `_cofnij_sposob`:

```python
    if cofniecie:
        if not w_calosci and any(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne_produkty(order)):
            raise LogistykaBlad(...)            # dotychczasowy komunikat bez zmian
        if w_calosci:
            _cofnij_do_pakowania(order, stary, None, user_id, teraz)
        usunieto = _zdejmij_z_trasy(przystanek, order, user_id) if przystanek is not None else None
        wynik = _cofnij_sposob(order, stary, user_id, teraz)
        wynik['przepakowanie'] = bool(w_calosci)
        wynik['usunieto_z_trasy'] = usunieto
        return wynik
```

- Wydziel dotychczasowy blok `if przepakowanie:` (pętla po spakowanych, 138620, log `przepakowanie`, baner, `weryfikacja.uniewaznij_etapy`) do `_cofnij_do_pakowania(order, stary, nowy, user_id, teraz)`. Lista spakowanych liczona wewnątrz. Baner:

```python
    tekst = sposoby.PRZEPAKUJ_NA_KURIERA if (nowy == sposoby.KURIER and stary in (sposoby.TRANSPORT, sposoby.ODBIOR)) \
        else sposoby.baner_logistyki(nowy)
    if sposoby.baner_systemowy(order.repack_reason):
        order.repack_reason = tekst
```

  Log `przepakowanie` przyjmuje `nowy` (None przy „Nie ustawiono”). Reguła: `weryfikacja.uniewaznij_etapy(order, teraz, u'cofnięcie do pakowania z panelu', user_id=user_id)`.
- W głównej ścieżce: `przepakowanie_zrob = decyzja if w_calosci else (nowy == sposoby.KURIER and stary in (sposoby.TRANSPORT, sposoby.ODBIOR) and bool(spakowane))`. Wynik `{'przepakowanie': przepakowanie_zrob, ...}`. Po zapisie nowego sposobu, gdy nie przepakowujemy w tym wywołaniu, zawołaj `_odswiez_baner_logistyki(order, nowy)`. Zrób to PRZED istniejącym `_zdejmij_baner_przepakowania_na_kuriera`, który zdejmuje tylko baner kuriera.
- W `_cofnij_sposob` (ścieżka „Nie ustawiono” bez spakowanych pozycji) zawołaj `_odswiez_baner_logistyki(order, None)` przed logiem.

- [ ] **Step 4: Endpoint** `panel_api.delivery_method`

```python
    przepakowanie = dane.get('przepakowanie')
    if przepakowanie is not None and not isinstance(przepakowanie, bool):
        return _blad(u'Pole przepakowanie musi mieć wartość true albo false.', 422)
    user_id = _user_id()      # PRZED _zapis_pod_blokada: po commicie current_user.id to zwykły SELECT (migawka)
    _zapis_pod_blokada()
    # Spec 8.7: wiersze zamówień FOR UPDATE rosnąco po id (jak hurt statusu i cron), potem zwykły odczyt z pozycjami.
    # Migawka powstaje dopiero teraz, więc decyzja „w całości spakowane” widzi wszystko, co zatwierdzono przed blokadami.
    # Pozycji nie blokujemy: stanowiska biorą pozycję przed zamówieniem (1213).
    db.session.query(ProductionOrder.id).filter(ProductionOrder.id.in_(ids)) \
        .order_by(ProductionOrder.id).with_for_update().all()
    zamowienia = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                  .filter(ProductionOrder.id.in_(ids)).order_by(ProductionOrder.id).populate_existing().all())
```

W pętli: `delivery.ustaw_sposob_dostawy(order, sposob, user_id=user_id, przepakowanie=przepakowanie)`. Odmowy: `wpis = {'order_id': order.id, 'komunikat': e.komunikat}; wpis.update(e.dane or {}); bledy.append(wpis)`. Logi i `user_id` w `logger.info` biorą zmienną, nie `_user_id()`. Sprawdź `LogistykaBlad.__init__`: `self.dane` musi istnieć zawsze (domyślnie `{}`).

- [ ] **Step 5: Testy endpointu** (w tym samym pliku)

```python
def _post(client, ids, sposob, **extra):
    dane = {'order_ids': ids, 'sposob': sposob}
    dane.update(extra)
    return client.post(BASE + '/orders/delivery-method', json=dane)


def test_endpoint_bez_decyzji_nie_zmienia_i_zwraca_kod(app, client):
    with app.app_context():
        spak = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        nie = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        ids = [spak.id, nie.id]
    r = _post(client, ids, s.ODBIOR)
    assert r.status_code == 200
    j = r.get_json()
    assert j['zmienione'] == [ids[1]]
    [b] = j['bledy']
    assert b['order_id'] == ids[0] and b['kod'] == 'wymaga_decyzji_przepakowania'
    assert b['opcje'] == ['przepakuj', 'bez_przepakowania'] and b['komunikat']


def test_endpoint_z_decyzja_true_przepakowuje(app, client):
    with app.app_context():
        spak = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        i = spak.id
    j = _post(client, [i], s.TRANSPORT, przepakowanie=True).get_json()
    assert j['przepakowanie'] == [i] and j['zmienione'] == [i]


def test_endpoint_false_przy_obowiazkowym_w_bledach(app, client):
    with app.app_context():
        spak = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        i = spak.id
    j = _post(client, [i], s.KURIER, przepakowanie=False).get_json()
    assert j['zmienione'] == [] and j['bledy'][0]['kod'] == 'wymaga_przepakowania'


@pytest.mark.parametrize('wartosc', ['tak', 1, 0, [], {}])
def test_endpoint_zla_wartosc_przepakowania_422(client, wartosc):
    r = _post(client, [1], s.KURIER, przepakowanie=wartosc)
    assert r.status_code == 422


def test_endpoint_blokuje_zamowienia_przed_odczytem_pozycji(app, client):
    """Kolejność zapytań: SELECT zamówień ORDER BY id (FOR UPDATE na MySQL) przed SELECT pozycji i przed zapisami."""
    from sqlalchemy import event
    with app.app_context():
        a = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        b = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        ids = [b.id, a.id]
        zapytania = []
        silnik = db.engine

        def sluchaj(conn, cursor, statement, parameters, context, executemany):
            zapytania.append(statement)
        event.listen(silnik, 'before_cursor_execute', sluchaj)
        try:
            _post(client, ids, s.ODBIOR, przepakowanie=False)
        finally:
            event.remove(silnik, 'before_cursor_execute', sluchaj)
    i_zam = next(i for i, q in enumerate(zapytania)
                 if q.lstrip().upper().startswith('SELECT prod_orders.id'.upper()) and 'ORDER BY' in q.upper())
    i_poz = next(i for i, q in enumerate(zapytania) if 'FROM prod_products' in q)
    i_upd = next(i for i, q in enumerate(zapytania) if q.lstrip().upper().startswith('UPDATE'))
    assert i_zam < i_poz < i_upd
```

(Jeśli prefiks SQL w SQLite różni się nazwą tabeli albo aliasem, dopasuj predykaty tak, żeby test padał bez blokady zamówień z kroku 4. Sprawdź to, cofając na chwilę blokadę.)

- [ ] **Step 6: Dostosuj istniejące testy**

Uruchom pełny pakiet z wynikiem do pliku: `docker compose -p <projekt> run --rm --no-deps app pytest tests/ -q -p no:cacheprovider > wynik.txt 2>&1`. Testy, które padną, zmieniają sposób zamówienia w całości spakowanego bez decyzji. Reguła:

- Dawne automatyczne przepakowanie (zmiana na kuriera z transportu albo odbioru) dostaje `przepakowanie=True`. W endpoincie: `"przepakowanie": true`.
- Dawna zmiana bez przepakowania dostaje `przepakowanie=False`.
- Test dawnego błędu „nie da się cofnąć do »Nie ustawiono«” na zamówieniu w całości spakowanym: zamień go na asercję `kod == 'wymaga_decyzji_przepakowania'` z `opcje == ['przepakuj']`. Dla częściowo spakowanego dawny błąd zostaje.

Nie zmieniaj asercji poza tymi, które opisują zachowanie zastąpione przez spec 8.7. Każdą zmienioną asercję wypisz w raporcie.

- [ ] **Step 7: Testy i commit**

Uruchom nowy plik i pełny pakiet (raz, wynik do pliku). Oczekiwane: wszystko zielone, a liczba testów = punkt wyjścia + nowe.

```bash
git add modules/production/logistics/sposoby.py modules/production/logistics/services/delivery.py \
  modules/production/logistics/routers/panel_api.py tests/
git commit -m "feat(production): zmiana sposobu dostawy spakowanego zamowienia wymaga decyzji o przepakowaniu"
```

### Task 2: Front — okno decyzji w zakładce Logistyka

**Files:**
- Modify: `modules/production/logistics/templates/logistics/tab_content.html` (nowy `<dialog>`)
- Modify: `modules/production/logistics/static/js/logistics.js` (`wyslijSposob`, `zmianaSelecta`, `zmienSposobZMapy`, `hurtowo`, `hurtSposob`, `hurtPodpowiedzi`, `podsumujZmiany`)
- Modify: `modules/production/logistics/static/css/logistics.css` (tylko jeśli istniejące klasy `lg-dialog*` nie wystarczą)
- Modify: plik szablonu dołączający `logistics.js` / `logistics.css` (podbicie `?v=`)
- Test: `tests/test_logistyka_okno_przepakowania_ui.py` (nowy, statyczny jak `tests/test_weryfikacja_panel.py`)

**Interfaces:**
- Consumes: kontrakt z sekcji „Kontrakt” (pole `przepakowanie`, `bledy[].kod`, `bledy[].opcje`, `przepakowanie` w odpowiedzi). Pola wiersza: `sposob` (kod albo null), `spakowane` (bool: w całości spakowane lub dalej), `numer`.
- Produces: nic dla innych zadań.

Projekt UI (skill `frontend-design:frontend-design`, styl istniejących okien zakładki: `lg-dialog`, `lg-dialog-tytul`, `lg-dialog-opis`, `lg-dialog-akcje`, przyciski jak w oknie adresu):

- Jedno okno `<dialog class="lg-dialog" data-lg="przepakowanie-dialog" aria-labelledby="lg-przepak-tytul">` z dynamiczną treścią.
- Tytuł: „Zamówienie {nr} jest spakowane” albo „{N} z zaznaczonych zamówień jest w całości spakowanych”.
- Opis mówi wprost, co zrobi każdy wybór:
  - „Cofnij do pakowania”: pozycje wracają do pakowania, paczki i etykiety paczek przestają obowiązywać, Base. dostaje status „Produkcja zakończona”, a tablet pokaże baner;
  - „Zmień bez przepakowania”: nowy sposób i status Base. dla nowego sposobu, a etykiety paczek trzeba przedrukować (ikona w wierszu);
  - przy przepakowaniu obowiązkowym: zdanie dlaczego (zmiana na „Nie ustawiono” albo na kuriera z transportu/odbioru).
- Przyciski: „Cofnij do pakowania” (główny), „Zmień bez przepakowania” (tylko gdy dozwolony dla choć jednego zamówienia), „Anuluj”. Esc i klik w tło = Anuluj.
- Drugie okno (decyzja Konrada 2) to to samo `<dialog>` w drugim kroku. Pojawia się po „Zmień bez przepakowania”, gdy w partii są zamówienia z przepakowaniem obowiązkowym. Tytuł: „{K} z nich wymaga cofnięcia do pakowania”, plus lista numerów (do 10, potem „i N innych”). Przyciski: „Cofnij je do pakowania”, „Pomiń je”, „Anuluj”, które anuluje całą zmianę.
- Bez animacji wejścia (styl panelu), fokus na pierwszym przycisku, po zamknięciu wraca na element, który otworzył okno.

Logika (`logistics.js`):

```javascript
    // Spec 8.7: czy zmiana zamówienia w całości spakowanego wymaga przepakowania (bez wyboru „bez”).
    function przepakowanieObowiazkowe(w, sposob) {
        return sposob === 'brak' || (sposob === 'kurier_baselinker'
            && (w.sposob === 'transport_woodpower' || w.sposob === 'odbior_osobisty'));
    }

    /**
     * Okno decyzji (spec 8.7). `wiersze` = zamówienia w całości spakowane z partii, `sposob` docelowy.
     * Zwraca Promise<{przepakuj: [id], bez: [id], pomin: [id]} | null> (null = Anuluj, nic nie wysyłamy).
     */
    function zapytajOPrzepakowanie(wiersze, sposob) { /* … dwa kroki jak w projekcie UI … */ }
```

- `wyslijSposob(ids, sposob, przepakowanie)` dokłada `przepakowanie` do ciała tylko wtedy, gdy nie jest `undefined`.
- Select w wierszu i dymek mapy: gdy `w.spakowane && sposob !== (w.sposob || 'brak')` → `zapytajOPrzepakowanie([w], sposob)`. `null` → `odswiezWiersz(id, false)` i koniec. Inaczej jedno żądanie z `przepakowanie: true` albo `false`.
- Hurt (`hurtowo` dostaje listę `{sposob, ids, przepakowanie}` zamiast `Map(sposob → ids)`; `hurtSposob` i `hurtPodpowiedzi` budują ją po oknie): niespakowane idą bez pola, a spakowane wg decyzji. Pominięte nie idą wcale i dostają komunikat `info` „Pominięto (wymagają cofnięcia do pakowania): {numery}.” Dla podpowiedzi z różnymi sposobami okno jest jedno dla całej partii, a „obowiązkowe” liczy się per zamówienie względem jego sposobu docelowego. Paczki po 500 id jak dotąd.
- Odpowiedź z `bledy[].kod === 'wymaga_decyzji_przepakowania'` (dane z przeglądarki były nieaktualne): wyjmij te wpisy z komunikatu błędów, pokaż okno dla tych zamówień (wiersze z `wynik.orders`) i wyślij je ponownie z decyzją. Robimy to raz. Jeśli druga odpowiedź znów ma ten kod, pokaż go jak zwykłą odmowę.
- `podsumujZmiany`: komunikat o przepakowaniu bez słowa „na kuriera”: „Zamówienie {nr} wraca do pakowania.” albo „Wracają do pakowania: {numery}.”
- Podbij `?v=` przy `logistics.js` (i `logistics.css`, jeśli zmieniony) w szablonie, który je dołącza.

- [ ] **Step 1: Test statyczny (failing)** `tests/test_logistyka_okno_przepakowania_ui.py`, wzorem `tests/test_weryfikacja_panel.py` (czyta plik i szuka wzorców):

```python
# -*- coding: utf-8 -*-
"""Krok 4.3, spec 8.7: okno decyzji o przepakowaniu w zakładce Logistyka (testy statyczne frontu)."""
import os
import re

KATALOG = os.path.join(os.path.dirname(__file__), '..', 'modules', 'production', 'logistics')


def _plik(*czesci):
    with open(os.path.join(KATALOG, *czesci), encoding='utf-8') as f:
        return f.read()


def test_szablon_ma_okno_przepakowania():
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert re.search(r'<dialog[^>]+data-lg="przepakowanie-dialog"', html)
    assert 'Cofnij do pakowania' in html and 'Anuluj' in html


def test_js_wysyla_decyzje_i_obsluguje_kod_serwera():
    js = _plik('static', 'js', 'logistics.js')
    assert 'przepakowanie:' in js or "przepakowanie'" in js
    assert 'wymaga_decyzji_przepakowania' in js
    assert re.search(r'function przepakowanieObowiazkowe\(', js)
    assert re.search(r'function zapytajOPrzepakowanie\(', js)


def test_js_anuluj_nic_nie_wysyla():
    js = _plik('static', 'js', 'logistics.js')
    # Po null z okna (Anuluj) ścieżki select / dymek / hurt kończą się przed wyslijSposob.
    assert re.search(r'zapytajOPrzepakowanie\([^)]*\)[\s\S]{0,400}?if \(!decyzja\)', js)


def test_js_komunikat_przepakowania_bez_kuriera():
    js = _plik('static', 'js', 'logistics.js')
    assert 'czeka na przepakowanie na kuriera' not in js
```

(Nazwę zmiennej `decyzja` i dokładny wzorzec dopasuj do kodu, byle test pilnował, że po anulowaniu nie idzie żądanie.)

- [ ] **Step 2: Implementacja** według projektu UI i logiki wyżej.
- [ ] **Step 3: Oględziny we wbudowanej przeglądarce** (narzędzia `mcp__Claude_Browser__*`, nigdy Chrome). Tymczasowy serwer z worktree zadania na wolnym porcie 127.0.0.1, sesja przez `login_user` w skrypcie (pamięć: podgląd strony bez logowania). Sprawdź:
  - zamówienie w całości spakowane, zmiana kurier → odbiór: trzy przyciski;
  - transport → kurier: dwa przyciski;
  - hurt z zamówieniem obowiązkowym i dobrowolnym, „Zmień bez przepakowania”: drugie okno;
  - Anuluj: brak żądania w zakładce sieci.

  Zrzuty z opisem do raportu. Serwer zatrzymaj.
- [ ] **Step 4: Testy i commit**

Uruchom test statyczny i pakiet UI logistyki (`tests/test_logistyka_*ui*.py tests/test_logistyka_zakladka.py tests/test_logistyka_okno_przepakowania_ui.py`). Pełny pakiet raz przed commitem.

```bash
git add modules/production/logistics/templates modules/production/logistics/static tests/test_logistyka_okno_przepakowania_ui.py
git commit -m "feat(production): okno decyzji o przepakowaniu przy zmianie sposobu dostawy w panelu Logistyki"
```

### Task 3: MySQL, podgląd 5005, dokumentacja

**Files:**
- Modify: `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` (sekcja 8.7: odstępstwa z realizacji, wynik wyścigów)
- Skrypty poza repo: `Documents/woodpower-podglady/logistyka43/kod/_weryfikacja_wyscigi.py` (nowe tryby)

- [ ] **Step 1:** Odśwież podgląd 5005 do HEAD gałęzi: `git archive HEAD | tar -x -C …/logistyka43/kod` i restart kontenera `logistyka43-podglad`. Podgląd 5004 nie jest już zamrożony, ale nie jest potrzebny.
- [ ] **Step 2: Wyścigi na dwóch sesjach MySQL**. Panel jest klientem testowym z sesją przez `login_user`. Tryby, każdy ×20 na czystej barierze i ×12 z jitterem 0–40 ms:
  - `panel-zakoncz`: zmiana sposobu z `przepakowanie=true` ∥ ostatnie „ZAKOŃCZ” pakowania tego zamówienia;
  - `panel-deklaracja`: zmiana z `przepakowanie=true` ∥ `PUT …/packages` tego zamówienia;
  - `panel-weryfikacja`: zmiana z `przepakowanie=true` ∥ weryfikacja ostatniej paczki z telefonu;
  - `panel-hurt-cron`: hurt dwóch zamówień ∥ cron logistyki.

  Niezmienniki:
  - po przepakowaniu brak ważnych paczek i `verified_at`;
  - pozycje `czeka_na_pakowanie`;
  - nigdy `zweryfikowane` z nowym sposobem bez decyzji;
  - na cofniętym zamówieniu zero ważnych paczek (`voided_at IS NULL`); prośba centrali.

  Kryterium (prośba centrali): zero 1213 w `panel-zakoncz` i `panel-deklaracja` (kilkadziesiąt przebiegów każdy). Każde 1213 to STOP: mechanizm z `SHOW ENGINE INNODB STATUS` idzie do kontrolera, a decyzja zapada przed zamknięciem kroku. Znane ryzyko do sprawdzenia: reguła `uniewaznij_etapy` przy pracy blokuje pozycje pod blokadą zamówienia, a ostatnie „ZAKOŃCZ” trzyma pozycję i sięga po zamówienie.

  Zapisz liczby i mechanizm każdego 1213 (`SHOW ENGINE INNODB STATUS`).
- [ ] **Step 3:** Odtwórz bazę pod oględziny (`_ogledziny_przygotuj.py`). Dopisz 2 zamówienia w całości spakowane do oględzin okna: jedno transport (do zmiany na kuriera, przepakowanie obowiązkowe) i jedno kurier (do zmiany na odbiór, dobrowolne). Numery wpisz do raportu.
- [ ] **Step 4:** Spec 8.7: odstępstwa z realizacji i jedno zdanie o wyniku wyścigów. Commit `git add -f` (`docs: krok 4.3 logistyki - zmiana sposobu spakowanego zamowienia, wyniki`).
- [ ] **Step 5:** Pełny pakiet raz. Kompilacja i składnia pod Pythona 3.9 dla plików `.py` zmienionych w Task 1–3.

## Wdrożenie

Bez migracji i bez zmian w appce: baner `repack_reason` jest już w kontrakcie 4.3 (kształt 5) i pokazuje tekst serwera. Sesja appki dostaje informację o nowych tekstach banera. Front i backend wchodzą razem, a stary JS z otwartej karty dostaje czytelną odmowę.
