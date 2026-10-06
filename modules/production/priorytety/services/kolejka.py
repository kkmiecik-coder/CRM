# -*- coding: utf-8 -*-
"""
Kolejka produkcji: ranga zamówień i pozycji oraz kolejność kafli stanowiska.

Źródło reguł: spec 2026-10-04-priorytety-produkcji-design.md, sekcje 3.1–3.2 (drabina, kolejność w szczeblu),
4.2 (algorytm), 4.5 (zasady brzegowe), 5.6 (stanowiska zamówieniowe), oraz decyzje Konrada z 5.10 po symulacji
na danych produkcyjnych: próg „Blisko terminu” 3 dni robocze, grupa materiału = (gatunek, klasa, grubość) ułożona
po najbliższym terminie w grupie, w grupie termin przed długością, „Blisko terminu” nad „Rozpoczęte”. Wzorcem
algorytmu jest skrypt `scripts/symulacja_priorytetow.py` (celowo nie importuje aplikacji — to osobna kopia).

Część czysta (pierwsza połowa modułu) pracuje na migawce — zwykłych strukturach, bez bazy i bez Flaska:
- `policz(migawka)` — ranga zamówień aktywnych (1..M) i ich pozycji,
- `kandydaci_stanowiska(...)` — kolejność kafli stanowiska przy pobieraniu na stół, z tagiem „Rozpoczęte”
  liczonym na żywo ze statusów pozycji.

Część z bazą (druga połowa): `utrwal()` czyta migawkę i zapisuje zmienione rangi na WŁASNEJ sesji;
`utrwal_po_commicie()` oraz `zaplanuj_po_commicie()` / `wykonaj_zaplanowane()` to wejścia dla routerów.
Modele i sesję importują dopiero funkcje tej części.
"""
import time
from collections import namedtuple
from datetime import date, datetime, timedelta

from modules.logging import get_structured_logger
from modules.production.priorytety import stale
from modules.production.services.station_catalog import STATION_PENDING_STATUS

# ── migawka: wejście `policz` ─────────────────────────────────────────────────────────────────────────────────
# zamowienia: {order_id: Zamowienie} — zamówienia aktywne (mają pozycję w STATUSY_PRODUKCJI); rank/rung to
#   bieżące wartości kolumn (pamięć podręczna), potrzebne tylko do wykrycia zmian przy zapisie.
# pozycje: [Pozycja] — WSZYSTKIE pozycje tych zamówień, także spakowane i anulowane (tag „Rozpoczęte”).
# trasa_zamowienia: {order_id: route_id} — przystanki na trasach roboczych/zatwierdzonych.
# trasy: {route_id: Trasa} — co najmniej trasy robocze/zatwierdzone.
# szczeble: [Szczebel] — wszystkie wiersze drabiny; ukrywanie szczebli tras nieaktywnych robi `policz`.
Migawka = namedtuple('Migawka', 'dzis prog_blisko_dni zamowienia pozycje trasa_zamowienia trasy szczeble')
Zamowienie = namedtuple('Zamowienie', 'id numer gwiazdki rank rung')
Pozycja = namedtuple('Pozycja', 'id order_id status deadline_date sequence dorobka created_at rank is_priority '
                                'manual_override')
Trasa = namedtuple('Trasa', 'id name date_from status')
Szczebel = namedtuple('Szczebel', 'id kind stars tag route_id position')

# ── wynik `policz` ────────────────────────────────────────────────────────────────────────────────────────────
# zamowienia: {order_id: RangaZamowienia}; `rung` = indeks 1-based w `drabina`; `szczebel` = rodzaj tekstem:
#   'trasa' | 'gwiazdki' | 'po_terminie' | 'blisko_terminu' | 'rozpoczete'; `tagi` = krotka w kolejności stale.TAGI.
# pozycje: {product_id: (priority_rank, is_priority)} — tylko pozycje aktywne.
# ostrzezenia: [str] — trasy bez szczebla, brakujące szczeble stałe.
# drabina: [klucz szczebla] po ukryciu tras nieaktywnych i wstawieniu szczebli wirtualnych.
Wynik = namedtuple('Wynik', 'zamowienia pozycje ostrzezenia drabina')
RangaZamowienia = namedtuple('RangaZamowienia', 'rank rung szczebel tagi termin')

# ── wejście i wynik `kandydaci_stanowiska` ────────────────────────────────────────────────────────────────────
# Pozycja w statusie stanowiska razem z polami zamówienia (numer, gwiazdki, termin, rung i rank z kolumn,
# na_trasie = przystanek na trasie roboczej/zatwierdzonej).
PozycjaStanowiska = namedtuple('PozycjaStanowiska', 'id order_id status dorobka created_at sequence gatunek klasa '
                                                    'grubosc dlugosc szerokosc numer gwiazdki termin rung rank '
                                                    'na_trasie')
Kandydaci = namedtuple('Kandydaci', 'kafle niekompletne')

# Zamówienie jeszcze bez utrwalonego szczebla (`priority_rung` NULL) sortuje się na końcu.
_KONIEC_DRABINY = 10 ** 6
# Największa kolejność pozycji mieszcząca się w numeracji jednego zamówienia (ranga × 100 + kolejność).
_MAKS_SEKWENCJA = stale.MNOZNIK_RANGI - 1


# ── pomocnicze czyste ─────────────────────────────────────────────────────────────────────────────────────────

def dodaj_dni_robocze(d, n):
    """Data `d` przesunięta o `n` dni roboczych (poniedziałek–piątek); n ≤ 0 → `d`."""
    wynik = d
    while n > 0:
        wynik += timedelta(days=1)
        if wynik.weekday() < 5:
            n -= 1
    return wynik


def _status(pozycja):
    """Status pozycji migawki (`status`) albo modelu ProductionProduct (`current_status`)."""
    status = getattr(pozycja, 'status', None)
    return status if status is not None else getattr(pozycja, 'current_status', None)


def termin_zamowienia(pozycje):
    """
    Termin zamówienia = najbliższy `deadline_date` jego pozycji AKTYWNYCH (w STATUSY_PRODUKCJI); None, gdy żadna
    aktywna pozycja nie ma terminu. Pozycja spakowana, wstrzymana albo anulowana nie wyciąga terminu.
    `pozycje` — obiekty z `deadline_date` i statusem w `status` albo `current_status`.
    """
    terminy = [p.deadline_date for p in pozycje
               if p.deadline_date is not None and _status(p) in stale.STATUSY_PRODUKCJI]
    return min(terminy) if terminy else None


def _etapy(statusy):
    """Etapy pozycji liczonych w kolejce: bez anulowanych, wstrzymanych i statusów spoza mapy etapów."""
    return [stale.ETAP_STATUSU[s] for s in statusy
            if s not in stale.STATUSY_POZA_KOLEJKA and s in stale.ETAP_STATUSU]


def rozpoczete(statusy):
    """
    Tag „Rozpoczęte” (spec 5.6): zamówienie ma pozycję na stanowisku zamówieniowym albo dalej (Formatowanie = etap
    2, Pakowanie = etap 5), a inną jeszcze wcześniej — czyli Formatowanie albo Pakowanie na nie czeka. Patrzy na
    statusy, nie na nazwę stanowiska: pozycja bez docięcia idzie ze Sklejania prosto do pakowania.
    `statusy` — statusy wszystkich pozycji zamówienia.
    """
    etapy = _etapy(statusy)
    etap_formatowania = stale.ETAP_STANOWISKA['formatting']
    etap_pakowania = stale.ETAP_STANOWISKA['packaging']
    return bool((any(e >= etap_formatowania for e in etapy) and any(e < etap_formatowania for e in etapy))
                or (any(e >= etap_pakowania for e in etapy) and any(e < etap_pakowania for e in etapy)))


def tagi_zamowienia(statusy, termin, dzis, prog_dni):
    """Zbiór tagów zamówienia: `po_terminie` (termin < dziś), `blisko_terminu` (dziś ≤ termin ≤ dziś + próg dni
    roboczych), `rozpoczete`. Zamówienie bez terminu nie dostaje tagów terminowych."""
    tagi = set()
    if termin is not None:
        if termin < dzis:
            tagi.add(stale.TAG_PO_TERMINIE)
        elif termin <= dodaj_dni_robocze(dzis, prog_dni):
            tagi.add(stale.TAG_BLISKO_TERMINU)
    if rozpoczete(statusy):
        tagi.add(stale.TAG_ROZPOCZETE)
    return tagi


def liczone_na_stanowisku(pary, stanowisko, omijajace=()):
    """
    Pozycje zamówienia liczone do kompletności na stanowisku (spec 5.6 p. 2): `pary` = [(product_id, status), …]
    bez anulowanych i wstrzymanych oraz bez pozycji, których ścieżka OMIJA to stanowisko (`omijajace` — zbiór ich
    id; np. pozycja bez docięcia nie idzie na Formatowanie). Taka pozycja nie trzyma zamówienia w „Niekompletnych”
    stanowiska, na które nigdy nie trafi, i nie wchodzi do mianownika „3/5 na stanowisku”. Wyjątek: pozycja
    omijająca, która mimo to STOI w statusie stanowiska (ręczna zmiana statusu), jest na nim i liczy się normalnie.
    """
    status_stanowiska = STATION_PENDING_STATUS[stanowisko]
    return [(product_id, status) for product_id, status in pary
            if status not in stale.STATUSY_POZA_KOLEJKA
            and (product_id not in omijajace or status == status_stanowiska)]


def kompletne_na_stanowisku(statusy, stanowisko, omija=None):
    """
    Czy zamówienie jest kompletne na stanowisku (spec 5.6 p. 2): żadna jego pozycja nie jest w statusie
    WCZEŚNIEJSZYM niż status tego stanowiska. Pozycje dalej liczą się jako zrobione; anulowane i wstrzymane
    nie blokują. `statusy` — statusy wszystkich pozycji zamówienia.

    `omija` — flagi równoległe do `statusy`: True = ścieżka tej pozycji omija stanowisko, więc pozycja nie liczy
    się do jego kompletności, nawet gdy stoi wcześniej (reguła `liczone_na_stanowisku`). None = nikt nie omija.
    Regułę ścieżki zna wołający (`widok.sciezka_omija` — z kodu routingu).
    """
    if omija is not None:
        omijajace = {i for i, flaga in enumerate(omija) if flaga}
        statusy = [status for _i, status in
                   liczone_na_stanowisku(list(enumerate(statusy)), stanowisko, omijajace)]
    etap = stale.ETAP_STANOWISKA[stanowisko]
    return all(e >= etap for e in _etapy(statusy))


def _klucz_numeru(numer):
    """Numer zamówienia do sortowania: same cyfry porządkujemy liczbowo (9999 przed 10000), resztę tekstowo."""
    numer = '' if numer is None else str(numer)
    if numer.isdigit():
        return (0, int(numer), '')
    return (1, 0, numer)


def klucz_zamowienia(pozycja_szczebla, gwiazdki, termin, numer):
    """Klucz kolejności zamówień (spec 3.2): szczebel, gwiazdki malejąco, termin (brak = na końcu), numer."""
    return (pozycja_szczebla, -gwiazdki, termin or date.max, _klucz_numeru(numer))


def _gwiazdki(wartosc):
    """Gwiazdki sprowadzone do 0..GWIAZDKI_MAX (NULL i wartości spoza zakresu nie wywracają przeliczenia)."""
    try:
        return max(0, min(stale.GWIAZDKI_MAX, int(wartosc or 0)))
    except (TypeError, ValueError):
        return 0


def _klucz_szczebla(szczebel):
    if szczebel.kind == 'stars':
        return ('stars', szczebel.stars)
    if szczebel.kind == 'tag':
        return ('tag', szczebel.tag)
    return ('route', szczebel.route_id)


def _trasa_na_drabinie(trasy, route_id):
    trasa = trasy.get(route_id)
    return trasa is not None and trasa.status in stale.STATUSY_TRASY_NA_DRABINIE


# ── policz ────────────────────────────────────────────────────────────────────────────────────────────────────

def _drabina(migawka, trasy_zamowien):
    """
    Lista kluczy szczebli w kolejności drabiny + ostrzeżenia. Szczeble tras spoza roboczych/zatwierdzonych są
    ukryte. Brakujące szczeble stałe dochodzą na końcu w kolejności domyślnej, a trasy z zamówieniami w produkcji
    bez własnego szczebla — w miejscu domyślnym (spec 3.1: pod najniższą trasą, a gdy tras nie ma, pod pięcioma
    gwiazdkami), rosnąco po id trasy. Wiersze w bazie dopisuje `drabina.uzupelnij()`; tu tylko liczymy tak, jakby
    już były.
    """
    drabina, ostrzezenia = [], []
    for szczebel in sorted(migawka.szczeble, key=lambda s: (s.position, s.id)):
        klucz = _klucz_szczebla(szczebel)
        if klucz in drabina:
            continue
        if klucz[0] == 'route' and not _trasa_na_drabinie(migawka.trasy, klucz[1]):
            continue
        drabina.append(klucz)

    for klucz in stale.DRABINA_DOMYSLNA:
        if klucz not in drabina:
            drabina.append(klucz)
            ostrzezenia.append('Brak szczebla %s %s na drabinie priorytetów — liczę go na końcu drabiny.' % klucz)

    for route_id in sorted(set(trasy_zamowien) - {k[1] for k in drabina if k[0] == 'route'}):
        indeksy_tras = [i for i, k in enumerate(drabina) if k[0] == 'route']
        miejsce = (indeksy_tras[-1] if indeksy_tras else drabina.index(('stars', stale.GWIAZDKI_MAX))) + 1
        drabina.insert(miejsce, ('route', route_id))
        ostrzezenia.append('Trasa %s nie ma szczebla na drabinie priorytetów — liczę ją w miejscu domyślnym.'
                           % route_id)
    return drabina, ostrzezenia


def policz(migawka):
    """
    Ranga zamówień aktywnych i ich pozycji (spec 4.2). Czysta funkcja: niczego nie czyta i nie zapisuje.

    Zamówienie z przystankiem na trasie roboczej/zatwierdzonej bierze szczebel trasy (gwiazdki i tagi nie
    wyciągają go ponad trasę); pozostałe — najwyższy ze swoich szczebli: gwiazdek i tagów. W szczeblu porządkują
    gwiazdki malejąco, potem termin, potem numer zamówienia.
    """
    pozycje_zamowien = {}
    for pozycja in migawka.pozycje:
        if pozycja.order_id in migawka.zamowienia:
            pozycje_zamowien.setdefault(pozycja.order_id, []).append(pozycja)

    aktywne = {}                # order_id → pozycje aktywne
    for order_id, pozycje in pozycje_zamowien.items():
        w_produkcji = [p for p in pozycje if p.status in stale.STATUSY_PRODUKCJI]
        if w_produkcji:
            aktywne[order_id] = w_produkcji

    trasa_zamowienia = {order_id: route_id for order_id, route_id in migawka.trasa_zamowienia.items()
                        if order_id in aktywne and _trasa_na_drabinie(migawka.trasy, route_id)}
    drabina, ostrzezenia = _drabina(migawka, trasa_zamowienia.values())
    pozycja_szczebla = {klucz: indeks + 1 for indeks, klucz in enumerate(drabina)}

    robocze = []                # (klucz sortowania, order_id, szczebel, tagi, termin, gwiazdki)
    for order_id, w_produkcji in aktywne.items():
        zamowienie = migawka.zamowienia[order_id]
        gwiazdki = _gwiazdki(zamowienie.gwiazdki)
        termin = termin_zamowienia(w_produkcji)
        tagi = tagi_zamowienia([p.status for p in pozycje_zamowien[order_id]], termin, migawka.dzis,
                               migawka.prog_blisko_dni)
        if order_id in trasa_zamowienia:
            szczebel = ('route', trasa_zamowienia[order_id])
        else:
            szczebel = min([('stars', gwiazdki)] + [('tag', t) for t in tagi], key=pozycja_szczebla.__getitem__)
        klucz = klucz_zamowienia(pozycja_szczebla[szczebel], gwiazdki, termin, zamowienie.numer) + (order_id,)
        robocze.append((klucz, order_id, szczebel, tagi, termin, gwiazdki))
    robocze.sort(key=lambda wiersz: wiersz[0])

    zamowienia, pozycje = {}, {}
    for ranga, (_klucz, order_id, szczebel, tagi, termin, gwiazdki) in enumerate(robocze, start=1):
        if szczebel[0] == 'route':
            nazwa = 'trasa'
        elif szczebel[0] == 'stars':
            nazwa = 'gwiazdki'
        else:
            nazwa = szczebel[1]
        zamowienia[order_id] = RangaZamowienia(
            rank=ranga, rung=pozycja_szczebla[szczebel], szczebel=nazwa,
            tagi=tuple(t for t in stale.TAGI if t in tagi), termin=termin)
        wyrozniona = gwiazdki >= 1 or stale.TAG_PO_TERMINIE in tagi
        for pozycja in aktywne[order_id]:
            if pozycja.dorobka:
                # Doróbka: zawsze pierwsza na każdym stanowisku, ramka na tablecie.
                pozycje[pozycja.id] = (0, True)
            else:
                sekwencja = min(max(int(pozycja.sequence or 0), 0), _MAKS_SEKWENCJA)
                pozycje[pozycja.id] = (ranga * stale.MNOZNIK_RANGI + sekwencja, wyrozniona)
    return Wynik(zamowienia=zamowienia, pozycje=pozycje, ostrzezenia=ostrzezenia, drabina=drabina)


# ── kandydaci stanowiska ──────────────────────────────────────────────────────────────────────────────────────

def _liczba(wartosc):
    try:
        return float(wartosc) if wartosc is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _szczebel_na_zywo(pozycja, zaczete, szczebel_rozpoczete):
    """Szczebel zamówienia przy pobieraniu na stół: kolumna `priority_rung`, a dla zamówienia rozpoczętego spoza
    trasy — szczebel tagu „Rozpoczęte”, jeśli stoi wyżej (ZAKOŃCZ zmienia statusy bez przeliczenia rang)."""
    szczebel = pozycja.rung if pozycja.rung is not None else _KONIEC_DRABINY
    if zaczete and not pozycja.na_trasie and szczebel_rozpoczete is not None:
        szczebel = min(szczebel, szczebel_rozpoczete)
    return szczebel


def kandydaci_stanowiska(stanowisko, pozycje, statusy_zamowien, szczebel_rozpoczete=None, jednostka=None,
                         omijajace=None):
    """
    Kolejność kafli stanowiska (spec 3.2, 5.6). Czysta funkcja.

    `pozycje` — `PozycjaStanowiska` w statusie tego stanowiska, już bez kafli leżących na stole i odłożonych
    (filtruje wołający). `statusy_zamowien` — {order_id: ((product_id, status), …)} dla WSZYSTKICH pozycji
    zamówienia: z nich liczony jest na żywo tag „Rozpoczęte” i kompletność. `szczebel_rozpoczete` — pozycja
    szczebla tagu „Rozpoczęte” na drabinie (`drabina.pozycja_tagu('rozpoczete')`); None = tag nie podnosi.
    `jednostka` — `pozycja` albo `zamowienie`; None = `zamowienie` na Formatowaniu i Pakowaniu, inaczej `pozycja`.
    `omijajace` — zbiór id pozycji (z `statusy_zamowien`), których ścieżka omija TO stanowisko; nie liczą się do
    kompletności zamówienia na nim (`liczone_na_stanowisku`). Tag „Rozpoczęte” dalej patrzy na wszystkie statusy.

    Jednostka `pozycja` → `kafle` = id pozycji: doróbki pierwsze (po `created_at`), dalej szczebel, gwiazdki,
    pozycje zamówień rozpoczętych, grupa materiału (gatunek, klasa, grubość) po najbliższym terminie w grupie,
    w grupie termin, długość i szerokość malejąco, numer zamówienia, kolejność pozycji; `niekompletne` = [].

    Jednostka `zamowienie` → `kafle` = id zamówień KOMPLETNYCH w kolejności klucza rangi (z tagiem na żywo;
    zamówienie z doróbką na tym stanowisku pierwsze), `niekompletne` = [(order_id, na_stanowisku, pozycji,
    brakuje)] w tej samej kolejności, gdzie `pozycji` = pozycje liczone do kompletności (bez anulowanych,
    wstrzymanych i omijających stanowisko), a `brakuje` = [(product_id, status), …] liczonych pozycji wcześniejszych
    niż stanowisko, rosnąco po id.
    """
    if jednostka is None:
        jednostka = 'zamowienie' if stanowisko in stale.STANOWISKA_ZAMOWIENIOWE else 'pozycja'
    pozycje = list(pozycje)
    zaczete = {order_id: rozpoczete([status for _id, status in pary])
               for order_id, pary in statusy_zamowien.items()}
    if jednostka == 'zamowienie':
        return _kafle_zamowien(stanowisko, pozycje, statusy_zamowien, zaczete, szczebel_rozpoczete,
                               frozenset(omijajace or ()))
    return Kandydaci(kafle=_kafle_pozycji(pozycje, zaczete, szczebel_rozpoczete), niekompletne=[])


def _kafle_pozycji(pozycje, zaczete, szczebel_rozpoczete):
    szczeble = {p.id: _szczebel_na_zywo(p, zaczete.get(p.order_id, False), szczebel_rozpoczete) for p in pozycje}

    def grupa(p):
        return (szczeble[p.id], p.gatunek or '?', p.klasa or '?', _liczba(p.grubosc))

    # Najbliższy termin w grupie materiału — przez wszystkie pozycje szczebla (także różnych gwiazdek).
    min_termin_grupy = {}
    for p in pozycje:
        termin = p.termin or date.max
        if grupa(p) not in min_termin_grupy or termin < min_termin_grupy[grupa(p)]:
            min_termin_grupy[grupa(p)] = termin

    def klucz(p):
        _szczebel, gatunek, klasa, grubosc = grupa(p)
        return (
            0 if p.dorobka else 1,
            (p.created_at or datetime.max) if p.dorobka else datetime.min,
            szczeble[p.id],
            -_gwiazdki(p.gwiazdki),
            0 if zaczete.get(p.order_id, False) else 1,
            min_termin_grupy[grupa(p)], gatunek, klasa, -grubosc,
            p.termin or date.max,
            -_liczba(p.dlugosc), -_liczba(p.szerokosc),
            _klucz_numeru(p.numer), p.sequence or 0, p.id,
        )

    return [p.id for p in sorted(pozycje, key=klucz)]


def _kafle_zamowien(stanowisko, pozycje, statusy_zamowien, zaczete, szczebel_rozpoczete, omijajace=frozenset()):
    etap = stale.ETAP_STANOWISKA[stanowisko]
    status_stanowiska = STATION_PENDING_STATUS[stanowisko]
    pozycje_zamowien = {}
    for p in pozycje:
        pozycje_zamowien.setdefault(p.order_id, []).append(p)

    wiersze = []                # (klucz, order_id, na_stanowisku, pozycji, brakuje)
    for order_id, tutaj in pozycje_zamowien.items():
        pierwsza = tutaj[0]     # pola zamówienia są te same na każdej jego pozycji
        pary = statusy_zamowien.get(order_id) or tuple((p.id, p.status) for p in tutaj)
        liczone = liczone_na_stanowisku(pary, stanowisko, omijajace)
        brakuje = sorted((pid, status) for pid, status in liczone
                         if status in stale.ETAP_STATUSU and stale.ETAP_STATUSU[status] < etap)
        na_stanowisku = sum(1 for _pid, status in liczone if status == status_stanowiska)
        dorobki = [p.created_at or datetime.max for p in tutaj if p.dorobka]
        szczebel = _szczebel_na_zywo(pierwsza, zaczete.get(order_id, False), szczebel_rozpoczete)
        klucz = ((0, min(dorobki)) if dorobki else (1, datetime.min)) + klucz_zamowienia(
            szczebel, _gwiazdki(pierwsza.gwiazdki), pierwsza.termin, pierwsza.numer) + (order_id,)
        wiersze.append((klucz, order_id, na_stanowisku, len(liczone), brakuje))
    wiersze.sort(key=lambda wiersz: wiersz[0])

    kafle = [order_id for _k, order_id, _n, _p, brakuje in wiersze if not brakuje]
    niekompletne = [(order_id, na_stanowisku, pozycji, brakuje)
                    for _k, order_id, na_stanowisku, pozycji, brakuje in wiersze if brakuje]
    return Kandydaci(kafle=kafle, niekompletne=niekompletne)


# ══ Część z bazą: migawka i zapis rang ════════════════════════════════════════════════════════════════════════
#
# `utrwal()` materializuje wynik `policz()` w kolumnach `prod_orders.priority_rank/priority_rung` oraz
# `prod_products.priority_rank/is_priority` — pamięci podręcznej dla czytelników SQL i starej appki (spec 4.2).
#
# KOLEJNOŚĆ BLOKAD (spec 9.4, CLAUDE.md „zamówienie najpierw”): zwykłe odczyty migawki → zamówienia FOR UPDATE
# rosnąco po id (tylko te, których wiersz albo pozycje się zmieniają) → pozycje tych zamówień FOR UPDATE rosnąco
# po id → same przypisania → jeden flush przy commicie (SQLAlchemy porządkuje UPDATE-y jednego mappera po kluczu
# głównym, zamówienia przed pozycjami). To sufiks łańcucha blokad Dostawy, hurtu, ZAKOŃCZ i doróbki, więc cyklu
# z nimi nie ma. `utrwal()` nie bierze blokady tras ani blokady stołu — trasy i drabinę tylko czyta. Rzadkie
# zakleszczenie 1213 (luki indeksów, pisarze pozycji bez blokady zamówienia): jedno ponowienie na nowej sesji.
#
# WŁASNA SESJA (jak dawne przeliczenie w priority_service, znalezisko z 22.09.2026): `utrwal()` zakłada i zamyka
# własną sesję i NIGDY nie dotyka `db.session` — ani commit, ani rollback, ani odczyt (autoflush wypchnąłby pracę
# wołającego i wziął blokady w jego transakcji). Dlatego próg „Blisko terminu” czyta własną sesją, a nie przez
# `config_service`.
#
# WARUNEK WSTĘPNY (MySQL): transakcja `db.session` wołającego nie ma niezatwierdzonych zapisów do `prod_orders`
# ani `prod_products`. Własna sesja to osobne połączenie w TYM SAMYM wątku — czekałaby na blokady wołającego,
# który czeka na nią; InnoDB nie widzi tego jako zakleszczenia i kończy `lock wait timeout` (1205).
# Wołać wyłącznie PO commicie: `utrwal_po_commicie()` w routerach panelu, `zaplanuj_po_commicie()` +
# `wykonaj_zaplanowane()` w API mobilnym (handler nie commituje — robi to `with_idempotency`).
#
# LIMIT CZEKANIA NA BLOKADĘ (K1-poprawka-1, znalezisko I2 przeglądu K1). Warunek wstępny jest tylko umową, a ręczna
# synchronizacja z Base. (`force_update`) potrafi go złamać: jej pętla zostawia w `db.session` zflushowany,
# niezatwierdzony zapis zamówienia. Z domyślnym limitem serwera (50 s) `utrwal` wisiałoby dłużej, niż gunicorn daje
# żądaniu (30 s). Dlatego własna sesja pracuje na JEDNYM przypiętym połączeniu, na którym przed pierwszym zapytaniem
# ustawiamy sesyjny `innodb_lock_wait_timeout` na LIMIT_CZEKANIA_NA_BLOKADE_S. Przekroczenie to błąd 1205: rollback,
# raport `success: False`, BEZ ponowienia (ponawiamy tylko zakleszczenie 1213) — rangi nadrobi następne przeliczenie
# albo cron. Krótki limit dotyczy każdego czekania tej sesji, także na zwykły ZAKOŃCZ czy hurt innego żądania; te
# trwają milisekundy, więc limit jest wyłącznie bezpiecznikiem.
#
# Przypięcie jest konieczne: sesja związana z silnikiem oddaje połączenie do puli przy każdym commicie i rollbacku,
# więc przebieg kontrolny mógłby dostać inne połączenie (bez limitu), a to z limitem trafiłoby do zwykłego żądania.
# Przed oddaniem połączenia limit wraca do wartości serwera (`= DEFAULT` to bieżąca wartość globalna); gdy się to nie
# uda (zerwane połączenie), połączenie unieważniamy — pula założy nowe, a krótki limit nie wycieknie do ZAKOŃCZ
# ani hurtu, które mają czekać tyle, co dotąd. Wybór „przywrócić”, nie „zawsze odłączyć”: przeliczenie idzie po
# większości akcji panelu, a nowe połączenie przy każdym z nich to zbędny koszt.
#
# PRZEBIEG KONTROLNY. Migawka jest zwykłym odczytem i poprzedza blokady, a zapis obejmuje tylko wiersze, które
# różniły się na TEJ migawce. Dwa przeliczenia naraz mogłyby więc zostawić mieszankę: przebieg, który zaczął przed
# cudzą zmianą, zapisuje rangi sprzed niej, a przeliczenie tej zmiany mogło skończyć wcześniej, nie znajdując nic do
# poprawienia. Dlatego po każdym zapisie `utrwal` czyta migawkę od nowa (nowa transakcja = świeży odczyt) i poprawia
# różnice, aż przebieg nie znajdzie żadnej — najwyżej _MAKS_PRZEBIEGOW razy. Każdy, kto zapisał, sprawdza po sobie,
# więc ostatni zapis w systemie zawsze kończy się kontrolą na stanie, który go obejmuje. Bez dodatkowej blokady:
# przeliczenie, które nie ma nic do zmiany, dalej nie blokuje niczego.
#
# Wobec zapisów, które nie wołają przeliczenia (ZAKOŃCZ na stanowisku), rangi mogą być chwilę nieaktualne. To pamięć
# podręczna: tag „Rozpoczęte” stół liczy na żywo, a cron nadrabia co godzinę.

logger = get_structured_logger('production.priorytety.kolejka')

# Znacznik w `g` żądania: po udanym commicie trzeba utrwalić rangi.
_PLAN_W_G = '_priorytety_utrwal_po_commicie'
# Zapis + poprawka po cudzej zmianie + kontrola. Gdy i trzeci przebieg coś zmienił, dane zmieniają się szybciej, niż
# nadążamy — kończymy z ostrzeżeniem, rangi poprawi przeliczenie tej kolejnej zmiany albo cron.
_MAKS_PRZEBIEGOW = 3
# Ile sekund własna sesja czeka na cudzą blokadę wiersza, zanim przeliczenie się podda (komentarz wyżej).
LIMIT_CZEKANIA_NA_BLOKADE_S = 5
_SQL_USTAW_LIMIT = 'SET SESSION innodb_lock_wait_timeout = %d' % LIMIT_CZEKANIA_NA_BLOKADE_S
_SQL_PRZYWROC_LIMIT = 'SET SESSION innodb_lock_wait_timeout = DEFAULT'
# Kod MySQL „Lock wait timeout exceeded”.
_KOD_LIMIT_CZEKANIA = 1205


def dzis():
    """Dzień (czas lokalny), względem którego `utrwal` liczy tagi terminowe. Osobna funkcja — testy ją zamrażają."""
    from modules.production.models import get_local_now
    return get_local_now().date()


def nowa_sesja():
    """
    Świeża, WŁASNA sesja `utrwal` — poza rejestrem `scoped_session`, więc jej commit i rollback dotyczą wyłącznie
    rang. Bez autoflushu: zapis idzie jednym flushem przy commicie. Testy podmieniają tę funkcję, żeby wstrzyknąć
    błąd commitu.

    Sesja jest przypięta do JEDNEGO połączenia (`sesja.bind`), wziętego z puli na cały czas przeliczenia — na nim
    obowiązuje limit czekania na blokadę („LIMIT CZEKANIA NA BLOKADĘ” wyżej). Zamyka ją `_zamknij` (sesja,
    przywrócenie limitu, oddanie połączenia do puli).
    """
    from extensions import db
    polaczenie = db.engine.connect()
    try:
        # `binds={}`: bez tego Flask-SQLAlchemy wpisuje mapę tabela → silnik, która wygrywa z `bind`, i sesja
        # brałaby połączenia z puli po swojemu.
        sesja = db.create_session({'bind': polaczenie, 'binds': {}})()
    except Exception:
        polaczenie.close()
        raise
    sesja.autoflush = False
    return sesja


def _ma_limit_czekania(polaczenie):
    """Czy baza tego połączenia zna `innodb_lock_wait_timeout` (MySQL). SQLite testów — nie."""
    return polaczenie.dialect.name == 'mysql'


def _wyslij_ustawienie(polaczenie, sql):
    """Ustawienie zmiennej sesji MySQL na połączeniu własnej sesji. Osobna funkcja — testy ją podglądają."""
    from sqlalchemy import text
    polaczenie.execute(text(sql))


def _ogranicz_czekanie(sesja):
    """Krótki limit czekania na blokadę na połączeniu własnej sesji — PRZED jej pierwszym zapytaniem."""
    polaczenie = sesja.bind
    if _ma_limit_czekania(polaczenie):
        _wyslij_ustawienie(polaczenie, _SQL_USTAW_LIMIT)


def _migawka(sesja):
    """
    Migawka dla `policz`, czytana zwykłymi odczytami sesji `sesja` (same kolumny — bez obiektów ORM): zamówienia
    aktywne, wszystkie ich pozycje, przystanki i trasy robocze/zatwierdzone, wszystkie szczeble, próg „Blisko
    terminu”. Niczego nie blokuje i niczego nie zapisuje.
    """
    from modules.production.logistics.models import Route, RouteStop
    from modules.production.models import ProductionOrder, ProductionProduct
    from modules.production.priorytety.models import PriorityRung
    from modules.production.priorytety.services import ustawienia

    w_produkcji = (sesja.query(ProductionProduct.order_id)
                   .filter(ProductionProduct.current_status.in_(stale.STATUSY_PRODUKCJI)))
    zamowienia = {
        w.id: Zamowienie(id=w.id, numer=w.internal_order_number, gwiazdki=w.priority_stars,
                         rank=w.priority_rank, rung=w.priority_rung)
        for w in sesja.query(ProductionOrder.id, ProductionOrder.internal_order_number,
                             ProductionOrder.priority_stars, ProductionOrder.priority_rank,
                             ProductionOrder.priority_rung)
        .filter(ProductionOrder.id.in_(w_produkcji))}
    pozycje = [
        Pozycja(id=w.id, order_id=w.order_id, status=w.current_status, deadline_date=w.deadline_date,
                sequence=w.product_sequence_in_order, dorobka=w.original_product_id is not None,
                created_at=w.created_at, rank=w.priority_rank, is_priority=bool(w.is_priority),
                manual_override=bool(w.priority_manual_override))
        for w in sesja.query(ProductionProduct.id, ProductionProduct.order_id, ProductionProduct.current_status,
                             ProductionProduct.deadline_date, ProductionProduct.product_sequence_in_order,
                             ProductionProduct.original_product_id, ProductionProduct.created_at,
                             ProductionProduct.priority_rank, ProductionProduct.is_priority,
                             ProductionProduct.priority_manual_override)
        .filter(ProductionProduct.order_id.in_(w_produkcji))]

    trasy = {
        w.id: Trasa(id=w.id, name=w.name, date_from=w.date_from, status=w.status)
        for w in sesja.query(Route.id, Route.name, Route.date_from, Route.status)
        .filter(Route.status.in_(stale.STATUSY_TRASY_NA_DRABINIE))}
    trasa_zamowienia = {}
    if trasy:
        for w in (sesja.query(RouteStop.order_id, RouteStop.route_id)
                  .filter(RouteStop.route_id.in_(sorted(trasy)))):
            trasa_zamowienia[w.order_id] = w.route_id

    szczeble = [
        Szczebel(id=w.id, kind=w.kind, stars=w.stars, tag=w.tag, route_id=w.route_id, position=w.position)
        for w in sesja.query(PriorityRung.id, PriorityRung.kind, PriorityRung.stars, PriorityRung.tag,
                             PriorityRung.route_id, PriorityRung.position)
        .order_by(PriorityRung.position, PriorityRung.id)]

    return Migawka(dzis=dzis(), prog_blisko_dni=ustawienia.prog_blisko(sesja), zamowienia=zamowienia,
                   pozycje=pozycje, trasa_zamowienia=trasa_zamowienia, trasy=trasy, szczeble=szczeble)


def _raport(start, success, wynik=None, zmienione_zamowienia=0, zmienione_pozycje=0, error=None):
    return {
        'success': success,
        'zamowien': len(wynik.zamowienia) if wynik is not None else 0,
        'pozycji': len(wynik.pozycje) if wynik is not None else 0,
        'zmienione_zamowienia': zmienione_zamowienia,
        'zmienione_pozycje': zmienione_pozycje,
        'ostrzezenia': list(wynik.ostrzezenia) if wynik is not None else [],
        'duration_seconds': round(time.monotonic() - start, 3),
        'error': error,
    }


def _utrwal_raz(sesja, zrodlo, user_id, start, licznik):
    """
    Jedna próba na sesji `sesja`: przebiegi (każdy we własnej transakcji), aż przebieg kontrolny nie znajdzie
    różnic — patrz „PRZEBIEG KONTROLNY” wyżej. `licznik` zbiera zapisane wiersze także przez ponowienie po 1213
    (zatwierdzone przebiegi pierwszej próby zostają w bazie). Błąd leci dalej.
    """
    for numer in range(1, _MAKS_PRZEBIEGOW + 1):
        # Wpis `przeliczenie` raz na wywołanie utrwal, w pierwszym przebiegu.
        wynik, zmienione_zamowienia, zmienione_pozycje = _przebieg(
            sesja, None if licznik['log'] else zrodlo, user_id, loguj_ostrzezenia=(numer == 1))
        licznik['log'] = licznik['log'] or bool(zrodlo)
        licznik['zamowienia'] += zmienione_zamowienia
        licznik['pozycje'] += zmienione_pozycje
        if not (zmienione_zamowienia or zmienione_pozycje):
            break
    else:
        logger.warning('Priorytety: rangi zmieniały się w każdym przebiegu przeliczenia — kończę, poprawi je '
                       'następne przeliczenie', extra={'przebiegi': _MAKS_PRZEBIEGOW})
    return _raport(start, True, wynik, licznik['zamowienia'], licznik['pozycje'])


def _przebieg(sesja, zrodlo, user_id, loguj_ostrzezenia=True):
    """
    Jeden przebieg w jednej transakcji sesji `sesja`: migawka → `policz` → blokady → zapis zmienionych → commit
    (albo rollback, gdy nic do zapisania). Zwraca (wynik `policz`, zapisane zamówienia, zapisane pozycje).
    """
    from sqlalchemy.orm import load_only

    from modules.production.models import ProductionOrder, ProductionProduct, get_local_now
    from modules.production.priorytety.models import PriorityLog

    migawka = _migawka(sesja)
    wynik = policz(migawka)
    if loguj_ostrzezenia:
        for ostrzezenie in wynik.ostrzezenia:
            logger.warning(ostrzezenie)

    do_zam = {order_id: ranga for order_id, ranga in wynik.zamowienia.items()
              if (migawka.zamowienia[order_id].rank, migawka.zamowienia[order_id].rung) != (ranga.rank, ranga.rung)}
    pozycje_migawki = {p.id: p for p in migawka.pozycje}
    do_poz = {}
    for product_id, (ranga, wyrozniona) in wynik.pozycje.items():
        pozycja = pozycje_migawki[product_id]
        # `priority_manual_override` jest martwe od P1 — zerujemy każde napotkane na pozycji aktywnej (spec 8.5).
        if pozycja.rank != ranga or pozycja.is_priority != wyrozniona or pozycja.manual_override:
            do_poz[product_id] = (ranga, wyrozniona)

    teraz = get_local_now()
    zmienione_zamowienia = zmienione_pozycje = 0
    if do_zam or do_poz:
        ids = sorted(set(do_zam) | {pozycje_migawki[product_id].order_id for product_id in do_poz})
        # Odczyty BIEŻĄCE i blokujące, zamówienia przed pozycjami. Tylko potrzebne kolumny: zamówienie niesie m.in.
        # etykietę kuriera (LONGTEXT), pozycja rysunki SVG. Między tymi odczytami a commitem żadnych zapytań.
        zamowienia = (sesja.query(ProductionOrder)
                      .options(load_only(ProductionOrder.priority_rank, ProductionOrder.priority_rung))
                      .filter(ProductionOrder.id.in_(ids)).order_by(ProductionOrder.id)
                      .with_for_update().populate_existing().all())
        pozycje = (sesja.query(ProductionProduct)
                   .options(load_only(ProductionProduct.order_id, ProductionProduct.current_status,
                                      ProductionProduct.priority_rank, ProductionProduct.is_priority,
                                      ProductionProduct.priority_manual_override))
                   .filter(ProductionProduct.order_id.in_(ids)).order_by(ProductionProduct.id)
                   .with_for_update().populate_existing().all())

        # Przypisania wyłącznie na obiektach z odczytu blokującego: zamówienie albo pozycja skasowane po migawce
        # nie wracają z tego odczytu, więc nie dostają rangi.
        for zamowienie in zamowienia:
            ranga = do_zam.get(zamowienie.id)
            if ranga is None:
                continue
            if (zamowienie.priority_rank, zamowienie.priority_rung) != (ranga.rank, ranga.rung):
                zamowienie.priority_rank = ranga.rank
                zamowienie.priority_rung = ranga.rung
                zmienione_zamowienia += 1
        for pozycja in pozycje:
            nowe = do_poz.get(pozycja.id)
            # Pozycja, która po migawce wyszła z produkcji (ZAKOŃCZ na pakowaniu, wstrzymanie), zostaje nietknięta.
            if nowe is None or pozycja.current_status not in stale.STATUSY_PRODUKCJI:
                continue
            ranga, wyrozniona = nowe
            zmiana = False
            if pozycja.priority_rank != ranga:
                pozycja.priority_rank = ranga
                zmiana = True
            if bool(pozycja.is_priority) != wyrozniona:
                pozycja.is_priority = wyrozniona
                zmiana = True
            if pozycja.priority_manual_override:
                pozycja.priority_manual_override = False
                zmiana = True
            if zmiana:
                # Świeży updated_at napędza ETag kolejki starej appki (spec 4.2).
                pozycja.updated_at = teraz
                zmienione_pozycje += 1

    if zrodlo:
        # Ręczne przeliczenie („Przelicz teraz”) zostawia ślad także wtedy, gdy niczego nie zmieniło. Cron
        # i wyzwalacze wołają bez źródła — co godzinę byłby to szum. Wpis bez order_id: bez FK do zamówień.
        sesja.add(PriorityLog(action='przeliczenie', note=str(zrodlo)[:255], new_value=str(zmienione_zamowienia),
                              user_id=user_id, created_at=teraz))
    if zmienione_zamowienia or zmienione_pozycje or zrodlo:
        sesja.commit()
        logger.info('Priorytety: utrwalono rangi', extra={
            'zamowien': len(wynik.zamowienia), 'pozycji': len(wynik.pozycje),
            'zmienione_zamowienia': zmienione_zamowienia, 'zmienione_pozycje': zmienione_pozycje,
            'zrodlo': zrodlo})
    else:
        sesja.rollback()
    return wynik, zmienione_zamowienia, zmienione_pozycje


def _cofnij(sesja):
    if sesja is None:
        return
    try:
        sesja.rollback()
    except Exception as e:      # rollback zerwanego połączenia nie może zasłonić pierwotnego błędu
        logger.error('Priorytety: nieudany rollback własnej sesji', extra={'error': str(e)})


def _zamknij(sesja):
    """
    Koniec własnej sesji: zamknięcie sesji (rollback tego, co otwarte), przywrócenie limitu czekania na jej
    połączeniu i oddanie połączenia do puli. Połączenie, któremu nie udało się przywrócić limitu, jest unieważniane
    — nie wraca do puli z krótkim limitem. Niczego nie rzuca.
    """
    if sesja is None:
        return
    polaczenie = getattr(sesja, 'bind', None)
    try:
        sesja.close()
    except Exception as e:
        logger.error('Priorytety: nieudane zamknięcie własnej sesji', extra={'error': str(e)})
    if polaczenie is None or not hasattr(polaczenie, 'invalidate'):
        return                  # sesja związana z silnikiem, nie z połączeniem: nie ma czego oddawać
    try:
        if _ma_limit_czekania(polaczenie):
            _wyslij_ustawienie(polaczenie, _SQL_PRZYWROC_LIMIT)
    except Exception as e:
        logger.warning('Priorytety: nie udało się przywrócić limitu czekania na blokadę — unieważniam połączenie',
                       extra={'error': str(e)})
        try:
            polaczenie.invalidate()
        except Exception as e2:
            logger.error('Priorytety: nieudane unieważnienie połączenia własnej sesji', extra={'error': str(e2)})
    try:
        polaczenie.close()
    except Exception as e:
        logger.error('Priorytety: nieudane oddanie połączenia własnej sesji', extra={'error': str(e)})


def utrwal(zrodlo=None, user_id=None):
    """
    Przelicza rangi i zapisuje zmienione wiersze — na WŁASNEJ sesji (warunek wstępny i kolejność blokad: komentarz
    nad tą częścią modułu). Każdy zapis to jedna transakcja; po zapisie idzie przebieg kontrolny na świeżej migawce
    (same odczyty, gdy rangi się zgadzają). Przeliczenie, które nie ma nic do zmiany, to jeden przebieg bez blokad.

    NIGDY nie rzuca i NIGDY nie dotyka `db.session`. Zwraca raport: `success`, `zamowien` i `pozycji` (aktywne),
    `zmienione_zamowienia`, `zmienione_pozycje` (zapisane wiersze, łącznie ze wszystkich przebiegów), `ostrzezenia`,
    `duration_seconds`, `error`. Dwie próby — druga tylko po zakleszczeniu MySQL 1213, na nowej sesji i od zera;
    drugie 1213 i każdy inny błąd → `success: False` (przebieg, który padł, niczego nie zapisał). Na cudzą blokadę
    wiersza czeka najwyżej LIMIT_CZEKANIA_NA_BLOKADE_S sekund (MySQL 1205 → `success: False` bez ponowienia).

    `zrodlo` (np. 'panel' dla „Przelicz teraz”) dopisuje wpis `przeliczenie` do `prod_priority_log`.
    """
    start = time.monotonic()
    licznik = {'zamowienia': 0, 'pozycje': 0, 'log': False}

    def porazka(blad):
        return _raport(start, False, zmienione_zamowienia=licznik['zamowienia'],
                       zmienione_pozycje=licznik['pozycje'], error=blad)

    try:
        from sqlalchemy.exc import OperationalError
        from modules.production.services.blokady_zamowien import kod_mysql

        for proba in (1, 2):
            sesja = None
            try:
                sesja = nowa_sesja()
                _ogranicz_czekanie(sesja)
                return _utrwal_raz(sesja, zrodlo, user_id, start, licznik)
            except OperationalError as e:
                _cofnij(sesja)
                if proba == 1 and kod_mysql(e) == 1213:
                    logger.warning('Priorytety: zakleszczenie 1213 przy zapisie rang, ponawiam raz na nowej sesji')
                    continue
                if kod_mysql(e) == _KOD_LIMIT_CZEKANIA:
                    # Ktoś trzyma blokadę zamówienia albo pozycji dłużej niż limit (np. niezatwierdzony zapis
                    # wołającego w tym samym wątku). Bez ponowienia: druga próba czekałaby na to samo.
                    logger.warning('Priorytety: przeliczenie rang przerwane — blokada zajęta dłużej niż limit '
                                   'czekania, rangi nadrobi następne przeliczenie albo cron',
                                   extra={'limit_s': LIMIT_CZEKANIA_NA_BLOKADE_S, 'proba': proba})
                    return porazka(str(e))
                logger.error('Priorytety: błąd zapisu rang', extra={'error': str(e), 'proba': proba})
                return porazka(str(e))
            except Exception as e:
                _cofnij(sesja)
                logger.error('Priorytety: błąd przeliczania rang', extra={'error': str(e), 'proba': proba})
                return porazka(str(e))
            finally:
                _zamknij(sesja)
    except Exception as e:      # siatka ostatniej szansy: kontrakt „nigdy nie rzuca”
        logger.error('Priorytety: nieoczekiwany błąd utrwal', extra={'error': str(e)})
    return porazka('nieoczekiwany blad utrwal')


def utrwal_po_commicie(zrodlo=None):
    """
    Przeliczenie rang po zdarzeniu, które zmienia kolejkę (spec 9.3) — wołać PO `db.session.commit()` w routerze
    panelu albo crona. Każde wywołanie przelicza (bez znacznika „raz na żądanie”: fikstury testów trzymają jeden
    kontekst aplikacji na wiele żądań, a przeliczenie bez zmian to same odczyty). Zwraca raport `utrwal` albo None,
    gdy poszedł wyjątek — ten trafia tylko do logu, odpowiedź routera zostaje nietknięta.
    """
    try:
        return utrwal(zrodlo=zrodlo)
    except Exception as e:
        logger.error('Priorytety: utrwal po commicie rzucił wyjątek', extra={'error': str(e)})
        return None


def zaplanuj_po_commicie():
    """
    API mobilne: handler nie commituje (robi to `with_idempotency`), więc tylko PLANUJE przeliczenie — znacznik
    w `g` żądania. Wykonuje je `wykonaj_zaplanowane()` po udanym commicie; przy rollbacku i powtórce idempotentnej
    znacznik ginie razem z `g` (jak plan dopychacza Base.).
    """
    from flask import g, has_request_context
    if has_request_context():
        setattr(g, _PLAN_W_G, True)


def porzuc_zaplanowane():
    """Rollback przed ponowieniem zapisu w tym samym żądaniu (1213 w zapisach Dostawy): plan pierwszej próby
    przepada razem z jej transakcją, druga próba planuje od nowa."""
    from flask import g, has_request_context
    if has_request_context():
        g.pop(_PLAN_W_G, None)


def wykonaj_zaplanowane():
    """Po commicie: przelicza rangi, jeśli handler to zaplanował. Zdejmuje znacznik, więc drugie wywołanie
    (i następne żądanie na tym samym kontekście aplikacji) niczego nie robi. Zwraca raport albo None."""
    from flask import g, has_request_context
    if not has_request_context():
        return None
    if not g.pop(_PLAN_W_G, False):
        return None
    return utrwal_po_commicie()
