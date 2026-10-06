# -*- coding: utf-8 -*-
"""
Odczyty dla panelu biura priorytetów (spec 2026-10-04, sekcje 3.1–3.2, 4.4, 5.1, 5.6, 7.1): drabina z licznikami
zamówień w produkcji i ostrzeżeniem o datach tras, kolejka zamówień, podgląd kolejki stanowiska i dane modalu
priorytetu zamówienia.

Wszystko tu to ZWYKŁE odczyty przez `db.session`: bez blokad, bez zapisów i bez commitów. Drabina, cała kolejka
i modal liczą szczebel, tagi i rangę na żywo (`kolejka.policz` na migawce z `kolejka._migawka`) — kolumny
`priority_rank`/`priority_rung` są pamięcią podręczną innych czytelników i mogą chwilę różnić się od panelu (do
najbliższego `utrwal()`). Wyjątek celowy: kolejka STANOWISKA czyta szczebel i rangę z kolumn, jak stół (spec 4.2),
bo ma pokazać dokładnie to, co stół weźmie — wejście do algorytmu buduje jedna funkcja `wejscie_kandydatow`, którą
woła też stół (K3).
"""
from collections import Counter

from sqlalchemy import or_
from sqlalchemy.orm import load_only, selectinload

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.models import Route, RouteStop
from modules.production.models import ProductionOrder, ProductionProduct, ProductionWorker, get_local_now
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog, PriorityRung, StationDesk
from modules.production.priorytety.services import drabina, kolejka, ustawienia
from modules.production.services import order_timeline_service
from modules.production.services.station_catalog import STATION_ORDER, STATION_PENDING_STATUS, station_label

# Kolumny pozycji potrzebne kolejce i modalowi (pozycja niesie też rysunki SVG — nie wczytujemy ich).
_KOLUMNY_POZYCJI = (
    ProductionProduct.id, ProductionProduct.order_id, ProductionProduct.short_product_id,
    ProductionProduct.current_status, ProductionProduct.original_product_id, ProductionProduct.created_at,
    ProductionProduct.product_sequence_in_order, ProductionProduct.configuration_id,
    ProductionProduct.parsed_length_cm, ProductionProduct.parsed_width_cm, ProductionProduct.parsed_thickness_cm,
    ProductionProduct.deadline_date,
    # ścieżka pozycji (`sciezka_omija`): docięcie, obróbka krawędzi, wykończenie
    ProductionProduct.cut_to_size, ProductionProduct.parsed_edge_processing, ProductionProduct.parsed_finish_type,
)

ETYKIETY_TAGOW = {
    stale.TAG_PO_TERMINIE: u'Po terminie',
    stale.TAG_BLISKO_TERMINU: u'Blisko terminu',
    stale.TAG_ROZPOCZETE: u'Rozpoczęte',
}
RODZAJ_SZCZEBLA = {'stars': 'gwiazdki', 'tag': 'tag', 'route': 'trasa'}


def _data(wartosc):
    return wartosc.isoformat() if wartosc is not None else None


def etykieta_gwiazdek(gwiazdki):
    """„★★★” albo „bez gwiazdek”."""
    return u'★' * gwiazdki if gwiazdki else u'bez gwiazdek'


def etykieta(rung):
    """Nazwa szczebla dla ludzi: gwiazdki, nazwa tagu albo nazwa trasy."""
    if rung.kind == 'stars':
        return etykieta_gwiazdek(rung.stars)
    if rung.kind == 'tag':
        return ETYKIETY_TAGOW.get(rung.tag, rung.tag)
    return rung.route.name if rung.route is not None else u'Trasa %s' % rung.route_id


def szczebel_json(rung, pozycja=None):
    """
    Szczebel drabiny w JSON panelu (wspólny serializer drabiny, kolejki i modalu). `pozycja` — indeks wśród szczebli
    WIDOCZNYCH (1-based); None → `drabina.pozycja_szczebla(rung)` (osobny odczyt drabiny; ukryty szczebel → None).
    """
    if pozycja is None:
        pozycja = drabina.pozycja_szczebla(rung)
    trasa = None
    if rung.kind == 'route' and rung.route is not None:
        trasa = {'id': rung.route.id, 'nazwa': rung.route.name, 'status': rung.route.status,
                 'date_from': _data(rung.route.date_from), 'date_to': _data(rung.route.date_to)}
    return {
        'id': rung.id,
        'rodzaj': RODZAJ_SZCZEBLA[rung.kind],
        'gwiazdki': rung.stars if rung.kind == 'stars' else None,
        'tag': rung.tag if rung.kind == 'tag' else None,
        'trasa': trasa,
        'pozycja': pozycja,
        'etykieta': etykieta(rung),
        'ruchomy': rung.kind != 'stars',
    }


def _dd_mm(wartosc):
    return wartosc.strftime('%d.%m') if wartosc is not None else '?'


def ostrzezenia_dat(szczeble_widoczne):
    """
    Ostrzeżenie o datach (spec 3.1): kolejne szczeble TRAS w widocznej drabinie (inne szczeble między nimi się nie
    liczą), gdzie wyższa trasa ma późniejsze `date_from` niż niższa. Jedno ostrzeżenie na parę; nic się nie przesuwa
    samo. Czysta funkcja na szczeblach z `kind`, `route_id` i `route` (`id`, `name`, `date_from`).
    """
    trasy = [s.route for s in szczeble_widoczne if s.kind == 'route' and s.route is not None]
    ostrzezenia = []
    for wyzsza, nizsza in zip(trasy, trasy[1:]):
        if wyzsza.date_from is not None and nizsza.date_from is not None and wyzsza.date_from > nizsza.date_from:
            ostrzezenia.append({
                'kod': 'daty_tras',
                'route_ids': [wyzsza.id, nizsza.id],
                'message': u'Trasa „{}” (od {}) stoi wyżej niż „{}” (od {}).'.format(
                    wyzsza.name, _dd_mm(wyzsza.date_from), nizsza.name, _dd_mm(nizsza.date_from)),
            })
    return ostrzezenia


def brakujace_szczeble_tras():
    """Id tras roboczych/zatwierdzonych bez wiersza w `prod_priority_rungs`, rosnąco."""
    wiersze = (db.session.query(Route.id)
               .outerjoin(PriorityRung, PriorityRung.route_id == Route.id)
               .filter(Route.status.in_(stale.STATUSY_TRASY_NA_DRABINIE), PriorityRung.id.is_(None))
               .order_by(Route.id).all())
    return [wiersz[0] for wiersz in wiersze]


def brak_szczebli():
    """Czy drabinie brakuje wierszy, które dopisuje `drabina.uzupelnij`: szczebla stałego albo szczebla trasy
    roboczej/zatwierdzonej. Warunek samonaprawy w `GET /drabina`."""
    stale_w_bazie = {(w.kind, w.stars if w.kind == 'stars' else w.tag)
                     for w in db.session.query(PriorityRung.kind, PriorityRung.stars, PriorityRung.tag)
                     .filter(or_(PriorityRung.kind == 'stars', PriorityRung.kind == 'tag'))}
    if any(klucz not in stale_w_bazie for klucz in stale.DRABINA_DOMYSLNA):
        return True
    return bool(brakujace_szczeble_tras())


def _widoczne_z_trasami():
    """Widoczne szczeble po `position`, z trasami wczytanymi jednym zapytaniem (bez zapytania na szczebel)."""
    widoczne = drabina.szczeble()
    route_ids = sorted({s.route_id for s in widoczne if s.kind == 'route'})
    if route_ids:
        Route.query.filter(Route.id.in_(route_ids)).all()   # mapa tożsamości: `rung.route` bez SELECT-a
    return widoczne


def drabina_panelu():
    """
    `{"szczeble": [...], "ostrzezenia": [...]}` — widoczne szczeble z licznikiem `w_produkcji` (zamówienia aktywne,
    których szczebel liczony na żywo to ten szczebel). Bez blokad i bez samonaprawy (czyta to też dashboard).
    """
    widoczne = _widoczne_z_trasami()
    wynik = kolejka.policz(kolejka._migawka(db.session))
    liczniki = Counter(wynik.drabina[ranga.rung - 1] for ranga in wynik.zamowienia.values())
    szczeble = []
    for pozycja, rung in enumerate(widoczne, start=1):
        wiersz = szczebel_json(rung, pozycja)
        wiersz['w_produkcji'] = liczniki.get(rung.klucz, 0)
        szczeble.append(wiersz)
    return {'szczeble': szczeble, 'ostrzezenia': ostrzezenia_dat(widoczne)}


# ── czytelnicy rangi poza panelem priorytetów (krok K4b; spec 7.2) ─────────────────────────────────────────────
# Szczeble „pilne” dla dashboardu: (rodzaj, gwiazdki albo tag); trasa liczy się każda (None = dowolna).
SZCZEBLE_PILNE = (('gwiazdki', 5), ('gwiazdki', 4), ('tag', stale.TAG_PO_TERMINIE), ('trasa', None))


def _pilny(szczebel):
    rodzaj = szczebel['rodzaj']
    if rodzaj == 'trasa':
        return ('trasa', None) in SZCZEBLE_PILNE
    wartosc = szczebel['gwiazdki'] if rodzaj == 'gwiazdki' else szczebel['tag']
    return (rodzaj, wartosc) in SZCZEBLE_PILNE


def liczba_pilnych_zamowien():
    """
    Zamówienia aktywne na szczeblach ★★★★★, ★★★★, „Po terminie” i trasach — suma liczników `w_produkcji`
    z `drabina_panelu()`, więc dashboard pokazuje tę samą liczbę co modal drabiny. Liczy ZAMÓWIENIA (nie pozycje).
    Czysty odczyt (bez blokad i bez samonaprawy).
    """
    return sum(szczebel['w_produkcji'] for szczebel in drabina_panelu()['szczeble'] if _pilny(szczebel))


def plakietka_szczebla(szczebel):
    """Tekst plakietki szczebla na karcie (monitor, zakładka): trasa „Trasa Śląsk · od 08.10”, tag — jego nazwa;
    szczebel gwiazdek nie ma plakietki (pokazują go same gwiazdki). `szczebel` — wynik `szczebel_json`."""
    if szczebel is None or szczebel['rodzaj'] == 'gwiazdki':
        return None
    if szczebel['rodzaj'] == 'trasa':
        tekst = u'Trasa %s' % szczebel['etykieta']
        data = (szczebel.get('trasa') or {}).get('date_from')
        if data:
            tekst += u' · od %s.%s' % (data[8:10], data[5:7])
        return tekst
    return szczebel['etykieta']


def priorytet_zamowien(order_ids):
    """
    {order_id: {"gwiazdki", "ranga", "szczebel", "plakietka"}} z KOLUMN pamięci podręcznej (`priority_stars`,
    `priority_rank`, `priority_rung`) — dla monitorów hali, które odświeżają się co 30 s i nie mogą liczyć całej
    kolejki (`policz`). Trzy zapytania na całą listę: kolumny zamówień, zbiór zamówień aktywnych, drabina (tylko gdy
    ktoś ma szczebel).

    `priority_rung` to indeks wśród szczebli WIDOCZNYCH (`drabina.szczeble()`), nie kolumna `position` — ta numeruje
    też ukryte szczeble tras załadowanych. Indeks spoza drabiny (trasa właśnie załadowana) → `szczebel`/`plakietka`
    None. Zamówienie nieaktywne (żadna pozycja w `STATUSY_PRODUKCJI`) ma w kolumnach rangę z ostatniego przeliczenia
    — tu `ranga`, `szczebel` i `plakietka` są None. Tag „Rozpoczęte”/„Po terminie” może być spóźniony do najbliższego
    `utrwal()` (cron co godzinę) — świadomie.
    """
    ids = sorted({int(order_id) for order_id in order_ids if order_id is not None})
    if not ids:
        return {}
    wiersze = (db.session.query(ProductionOrder.id, ProductionOrder.priority_stars, ProductionOrder.priority_rank,
                                ProductionOrder.priority_rung)
               .filter(ProductionOrder.id.in_(ids)).all())
    aktywne = {wiersz[0] for wiersz in (db.session.query(ProductionProduct.order_id)
                                        .filter(ProductionProduct.order_id.in_(ids),
                                                ProductionProduct.current_status.in_(stale.STATUSY_PRODUKCJI))
                                        .distinct())}
    widoczne = None
    wynik = {}
    for order_id, gwiazdki, ranga, rung in wiersze:
        wpis = {'gwiazdki': int(gwiazdki or 0), 'ranga': None, 'szczebel': None, 'plakietka': None}
        if order_id in aktywne:
            wpis['ranga'] = ranga
            if rung is not None:
                if widoczne is None:
                    widoczne = _widoczne_z_trasami()
                if 1 <= rung <= len(widoczne):
                    wpis['szczebel'] = szczebel_json(widoczne[rung - 1], rung)
                    wpis['plakietka'] = plakietka_szczebla(wpis['szczebel'])
        wynik[order_id] = wpis
    return wynik


# ── kolejka i modal priorytetu (spec 3.2, 5.1, 5.6, 7.1) ────────────────────────────────────────────────────

# Status pozycji → kod stanowiska, na którym czeka (odwrotność STATION_PENDING_STATUS).
STANOWISKO_STATUSU = {status: kod for kod, status in STATION_PENDING_STATUS.items()}
LIMIT_KOLEJKI = 50
LIMIT_KOLEJKI_MAX = 500
LIMIT_HISTORII = 50


def _liczba_cm(wartosc):
    return float(wartosc) if wartosc is not None else None


def _krotki(szczebel):
    """Szczebel w wierszu kolejki i kaflu: id, rodzaj, etykieta, pozycja."""
    if szczebel is None:
        return None
    return {k: szczebel[k] for k in ('id', 'rodzaj', 'etykieta', 'pozycja')}


def _szczebel_z_klucza(klucz, po_kluczu, indeks, nazwy_tras):
    """
    Szczebel panelu dla klucza z `Wynik.drabina`. `po_kluczu` — {klucz: (pozycja widoczna, wiersz)}. Klucz bez
    wiersza to szczebel wirtualny `policz` (trasa bez szczebla w oknie wdrożenia albo brakujący szczebel stały):
    bez `id`, z pozycją `indeks` z wyniku przeliczenia.
    """
    if klucz in po_kluczu:
        pozycja, rung = po_kluczu[klucz]
        return szczebel_json(rung, pozycja)
    rodzaj, wartosc = klucz
    if rodzaj == 'stars':
        nazwa = etykieta_gwiazdek(wartosc)
    elif rodzaj == 'tag':
        nazwa = ETYKIETY_TAGOW.get(wartosc, wartosc)
    else:
        nazwa = nazwy_tras.get(wartosc) or u'Trasa %s' % wartosc
    return {'id': None, 'rodzaj': RODZAJ_SZCZEBLA[rodzaj], 'gwiazdki': wartosc if rodzaj == 'stars' else None,
            'tag': wartosc if rodzaj == 'tag' else None, 'trasa': None, 'pozycja': indeks, 'etykieta': nazwa,
            'ruchomy': rodzaj != 'stars'}


def _trasa_krotka(trasa):
    if trasa is None:
        return None
    return {'id': trasa.id, 'nazwa': trasa.name, 'date_from': _data(trasa.date_from)}


def _na_zywo():
    """Widoczne szczeble, ich mapa po kluczu i wynik `policz` na migawce bez blokad."""
    widoczne = _widoczne_z_trasami()
    po_kluczu = {rung.klucz: (pozycja, rung) for pozycja, rung in enumerate(widoczne, start=1)}
    migawka = kolejka._migawka(db.session)
    return widoczne, po_kluczu, migawka, kolejka.policz(migawka)


def _etapy(statusy):
    """{kod stanowiska: liczba pozycji czekających na nim} w kolejności procesu."""
    liczniki = Counter(STANOWISKO_STATUSU[s] for s in statusy if s in STANOWISKO_STATUSU)
    return {kod: liczniki[kod] for kod in STATION_ORDER if liczniki.get(kod)}


def _wiersz_kolejki(order_id, ranga, migawka, wynik, po_kluczu, nazwy_tras):
    zamowienie = migawka.zamowienia[order_id]
    route_id = migawka.trasa_zamowienia.get(order_id)
    szczebel = _szczebel_z_klucza(wynik.drabina[ranga.rung - 1], po_kluczu, ranga.rung, nazwy_tras)
    return {
        'order_id': order_id,
        'numer': zamowienie.numer,
        'ranga': ranga.rank,
        'gwiazdki': int(zamowienie.gwiazdki or 0),
        'szczebel': szczebel,
        'tagi': list(ranga.tagi),
        'termin': _data(ranga.termin),
        'trasa': _trasa_krotka(migawka.trasy.get(route_id)) if route_id is not None else None,
    }


def kolejka_zamowien():
    """
    Cała kolejka zamówień aktywnych po randze liczonej na żywo (`policz`, Doprecyzowania p. 4). Zwraca
    `{"wyliczono", "lacznie", "zamowienia": [...]}`.
    """
    _widoczne, po_kluczu, migawka, wynik = _na_zywo()
    nazwy_tras = {route_id: trasa.name for route_id, trasa in migawka.trasy.items()}
    ids = sorted(wynik.zamowienia)
    klienci = {}
    if ids:
        klienci = dict(db.session.query(ProductionOrder.id, ProductionOrder.client_name)
                       .filter(ProductionOrder.id.in_(ids)).all())
    statusy = {}
    for pozycja in migawka.pozycje:
        statusy.setdefault(pozycja.order_id, []).append(pozycja.status)

    wiersze = []
    for order_id, ranga in sorted(wynik.zamowienia.items(), key=lambda para: para[1].rank):
        wiersz = _wiersz_kolejki(order_id, ranga, migawka, wynik, po_kluczu, nazwy_tras)
        wiersz['szczebel'] = _krotki(wiersz['szczebel'])
        etapy = _etapy(statusy.get(order_id, ()))
        wiersz.update({'klient': klienci.get(order_id), 'pozycji': sum(etapy.values()), 'etapy': etapy})
        wiersze.append(wiersz)
    return {'wyliczono': get_local_now().isoformat(timespec='seconds'), 'lacznie': len(wiersze),
            'zamowienia': wiersze}


# Stanowisko → „kropka” osi czasu zamówienia (`order_timeline_service.product_in_route`): Wycinanie i Składanie to
# dwa wejścia tego samego etapu.
_KROPKA_SCIEZKI = {'cutting': 'entry', 'assembly': 'entry'}


def sciezka_omija(pozycja, stanowisko):
    """
    Czy ścieżka pozycji OMIJA stanowisko (spec 5.6 p. 2). Reguła z kodu routingu, nie z nazwy stanowiska:
    `order_timeline_service.product_in_route` — odbicie `ProductionProduct.complete_task` (bez docięcia pozycja
    idzie ze Sklejania prosto do pakowania, omijając Formatowanie i Krawędzie; bez obróbki krawędzi omija Krawędzie;
    Lakiernia tylko dla olejowanych i lakierowanych; Pakowania nie omija nic). Czyta wyłącznie kolumny pozycji.
    """
    return not order_timeline_service.product_in_route(pozycja, _KROPKA_SCIEZKI.get(stanowisko, stanowisko))


def omijajace_stanowisko(stanowisko, pozycje):
    """Zbiór id pozycji (spośród `pozycje`), których ścieżka omija stanowisko — wejście `omijajace`
    `kolejka.kandydaci_stanowiska` i `kolejka.liczone_na_stanowisku`. Zero zapytań na wczytanych kolumnach."""
    return frozenset(pozycja.id for pozycja in pozycje if sciezka_omija(pozycja, stanowisko))


def wejscie_kandydatow(stanowisko, zamowienia, pozycje, trasa_zamowienia, desk_unit_keys):
    """
    Jedyne miejsce budowania wejścia do `kolejka.kandydaci_stanowiska` — dla podglądu w panelu i dla stołu
    (`stol.dopelnij` w K3), żeby oba liczyły z tego samego. Czysta funkcja na obiektach JUŻ wczytanych: zero zapytań,
    także leniwych relacji (wołający wczytuje `configuration` pozycji z wyprzedzeniem i nie oddaje obiektów
    wygaszonych przez commit).

    `zamowienia` — zamówienia (ORM) z co najmniej jedną pozycją w statusie stanowiska; `pozycje` — WSZYSTKIE pozycje
    tych zamówień (ORM); `trasa_zamowienia` — {order_id: route_id} przystanków na trasach roboczych/zatwierdzonych;
    `desk_unit_keys` — klucze wierszy stołu stanowiska (na stole i odłożone) w BIEŻĄCEJ jednostce stanowiska (wiersz
    z kluczem innej jednostki jest nieaktualny i nikogo nie ukrywa).

    Zwraca (lista `kolejka.PozycjaStanowiska` pozycji w statusie stanowiska bez kafli ze stołu, rosnąco po id;
    `statusy_zamowien` = {order_id: ((product_id, current_status), …)} dla wszystkich pozycji zamówienia, rosnąco
    po id). Szczebel i ranga zamówienia z kolumn `priority_rung`/`priority_rank` (jak stół, spec 4.2), termin
    z pozycji aktywnych. Anulowane i wstrzymane pomija sam algorytm; Pakowanie bez sposobu dostawy jest zwykłym
    kandydatem (logistyka 4.6, spec 5.1).
    """
    status = STATION_PENDING_STATUS[stanowisko]
    zamowienia_po_id = {zamowienie.id: zamowienie for zamowienie in zamowienia}
    pozycje_zamowien = {}
    for pozycja in sorted(pozycje, key=lambda p: p.id):
        if pozycja.order_id in zamowienia_po_id:
            pozycje_zamowien.setdefault(pozycja.order_id, []).append(pozycja)
    statusy_zamowien = {order_id: tuple((p.id, p.current_status) for p in lista)
                        for order_id, lista in pozycje_zamowien.items()}
    terminy = {order_id: kolejka.termin_zamowienia(lista) for order_id, lista in pozycje_zamowien.items()}

    wynik = []
    for order_id, lista in sorted(pozycje_zamowien.items()):
        zamowienie = zamowienia_po_id[order_id]
        for pozycja in lista:
            if pozycja.current_status != status:
                continue
            if 'p:%d' % pozycja.id in desk_unit_keys or 'o:%d' % order_id in desk_unit_keys:
                continue
            konfiguracja = pozycja.configuration
            wynik.append(kolejka.PozycjaStanowiska(
                id=pozycja.id, order_id=order_id, status=pozycja.current_status,
                dorobka=pozycja.original_product_id is not None, created_at=pozycja.created_at,
                sequence=pozycja.product_sequence_in_order,
                gatunek=konfiguracja.species if konfiguracja is not None else None,
                klasa=konfiguracja.wood_class if konfiguracja is not None else None,
                grubosc=pozycja.parsed_thickness_cm, dlugosc=pozycja.parsed_length_cm,
                szerokosc=pozycja.parsed_width_cm, numer=zamowienie.internal_order_number,
                gwiazdki=zamowienie.priority_stars, termin=terminy[order_id], rung=zamowienie.priority_rung,
                rank=zamowienie.priority_rank, na_trasie=order_id in trasa_zamowienia))
    wynik.sort(key=lambda p: p.id)
    return wynik, statusy_zamowien


def _prefiks_jednostki(jednostka):
    return 'o:' if jednostka == 'zamowienie' else 'p:'


def _dane_stanowiska(stanowisko):
    """
    Zwykły odczyt wszystkiego, czego potrzebuje kolejka stanowiska: zamówienia z pozycją w jego statusie (z
    pozycjami i konfiguracjami — trzy zapytania), przystanki tras roboczych/zatwierdzonych, wiersze stołu. Potem
    `wejscie_kandydatow` i `kolejka.kandydaci_stanowiska` (bez własnego sortowania). Bez blokad i zapisów.
    """
    status = STATION_PENDING_STATUS[stanowisko]
    jednostka = ustawienia.jednostka(stanowisko)
    w_statusie = db.session.query(ProductionProduct.order_id).filter(ProductionProduct.current_status == status)
    zamowienia = (ProductionOrder.query
                  .options(load_only(ProductionOrder.id, ProductionOrder.internal_order_number,
                                     ProductionOrder.priority_stars, ProductionOrder.priority_rank,
                                     ProductionOrder.priority_rung, ProductionOrder.override_delivery_method),
                           selectinload(ProductionOrder.products).load_only(*_KOLUMNY_POZYCJI),
                           selectinload(ProductionOrder.products).selectinload(ProductionProduct.configuration))
                  .filter(ProductionOrder.id.in_(w_statusie)).order_by(ProductionOrder.id).all())
    pozycje = [pozycja for zamowienie in zamowienia for pozycja in zamowienie.products]
    ids = [zamowienie.id for zamowienie in zamowienia]
    trasa_zamowienia = {}
    if ids:
        trasa_zamowienia = dict(db.session.query(RouteStop.order_id, RouteStop.route_id)
                                .join(Route, Route.id == RouteStop.route_id)
                                .filter(RouteStop.order_id.in_(ids),
                                        Route.status.in_(stale.STATUSY_TRASY_NA_DRABINIE)).all())
    stol = StationDesk.query.filter(StationDesk.station_code == stanowisko).order_by(StationDesk.id).all()
    prefiks = _prefiks_jednostki(jednostka)
    desk_unit_keys = {wiersz.unit_key for wiersz in stol if wiersz.unit_key.startswith(prefiks)}

    pozycje_stanowiska, statusy_zamowien = wejscie_kandydatow(stanowisko, zamowienia, pozycje, trasa_zamowienia,
                                                              desk_unit_keys)
    widoczne = _widoczne_z_trasami()
    szczebel_rozpoczete = drabina.pozycja_tagu(stale.TAG_ROZPOCZETE, widoczne)
    omijajace = omijajace_stanowisko(stanowisko, pozycje)
    kandydaci = kolejka.kandydaci_stanowiska(stanowisko, pozycje_stanowiska, statusy_zamowien,
                                             szczebel_rozpoczete=szczebel_rozpoczete, jednostka=jednostka,
                                             omijajace=omijajace)
    return {
        'stanowisko': stanowisko, 'omijajace': omijajace,
        'jednostka': jednostka, 'kandydaci': kandydaci, 'widoczne': widoczne,
        'szczebel_rozpoczete': szczebel_rozpoczete, 'statusy_zamowien': statusy_zamowien,
        'zamowienia': {zamowienie.id: zamowienie for zamowienie in zamowienia},
        'pozycje': {pozycja.id: pozycja for pozycja in pozycje},
        'pozycje_stanowiska': {pozycja.id: pozycja for pozycja in pozycje_stanowiska},
        'trasa_zamowienia': trasa_zamowienia, 'stol': stol,
    }


def _szczebel_kafla(dane, zamowienie, na_trasie, zaczete):
    """Szczebel, z którego kafel wchodzi na stół: kolumna `priority_rung`, a zamówienie rozpoczęte spoza trasy —
    szczebel „Rozpoczęte”, jeśli stoi wyżej (ta sama reguła co `kolejka.kandydaci_stanowiska`)."""
    rung = zamowienie.priority_rung
    rozpoczete_na = dane['szczebel_rozpoczete']
    if zaczete and not na_trasie and rozpoczete_na is not None and (rung is None or rozpoczete_na < rung):
        rung = rozpoczete_na
    widoczne = dane['widoczne']
    if rung is None or not 1 <= rung <= len(widoczne):
        return None
    return _krotki(szczebel_json(widoczne[rung - 1], rung))


def _sposob_ustawiony(zamowienie):
    """Pole informacyjne kafla Pakowania w podglądzie kolejki (K2). Od logistyki 4.6 niczego nie blokuje — zamówienie
    bez sposobu dostawy jest zwykłym kandydatem (spec 5.1)."""
    return sposoby.normalizuj(zamowienie.override_delivery_method) is not None


def _kafel_pozycji(dane, product_id):
    pozycja = dane['pozycje_stanowiska'][product_id]
    zamowienie = dane['zamowienia'][pozycja.order_id]
    zaczete = kolejka.rozpoczete([status for _id, status in dane['statusy_zamowien'][pozycja.order_id]])
    return {
        'product_id': pozycja.id,
        'short_id': dane['pozycje'][pozycja.id].short_product_id,
        'order_id': pozycja.order_id,
        'numer': pozycja.numer,
        'gwiazdki': int(pozycja.gwiazdki or 0),
        'szczebel': _szczebel_kafla(dane, zamowienie, pozycja.na_trasie, zaczete),
        'rozpoczete': zaczete,
        'dorobka': pozycja.dorobka,
        'termin': _data(pozycja.termin),
        'material': {'gatunek': pozycja.gatunek, 'klasa': pozycja.klasa, 'grubosc_cm': _liczba_cm(pozycja.grubosc)},
        'wymiary': {'dlugosc_cm': _liczba_cm(pozycja.dlugosc), 'szerokosc_cm': _liczba_cm(pozycja.szerokosc),
                    'grubosc_cm': _liczba_cm(pozycja.grubosc)},
    }


def _kafel_zamowienia(dane, order_id):
    zamowienie = dane['zamowienia'][order_id]
    pary = dane['statusy_zamowien'][order_id]
    zaczete = kolejka.rozpoczete([status for _id, status in pary])
    termin = kolejka.termin_zamowienia(dane['pozycje'][product_id] for product_id, _status in pary)
    return {
        'order_id': order_id,
        'numer': zamowienie.internal_order_number,
        'gwiazdki': int(zamowienie.priority_stars or 0),
        'szczebel': _szczebel_kafla(dane, zamowienie, order_id in dane['trasa_zamowienia'], zaczete),
        'termin': _data(termin),
        'pozycji': len(kolejka.liczone_na_stanowisku(pary, dane['stanowisko'], dane['omijajace'])),
        'sposob_dostawy_ustawiony': _sposob_ustawiony(zamowienie),
    }


def _niekompletne(dane, wiersz):
    order_id, na_stanowisku, pozycji, brakuje = wiersz
    return {
        'order_id': order_id,
        'numer': dane['zamowienia'][order_id].internal_order_number,
        'na_stanowisku': na_stanowisku,
        'pozycji': pozycji,
        'brakuje': [{'short_id': dane['pozycje'][product_id].short_product_id,
                     'stanowisko': STANOWISKO_STATUSU.get(status)} for product_id, status in brakuje],
    }


def kolejka_stanowiska(kod, limit=LIMIT_KOLEJKI):
    """
    Podgląd tego, co stół stanowiska `kod` wziąłby jako następne (Doprecyzowania p. 7): ten sam
    `kolejka.kandydaci_stanowiska` co stół, kafle ze stołu i odłożone pominięte. Kolejność kafli = wynik algorytmu.
    `limit` przycina listy kafli i niekompletnych (`lacznie` liczy wszystkie kafle). Nieznany kod → ValueError.
    """
    if kod not in STATION_PENDING_STATUS or kod in ustawienia.STANOWISKA_BEZ_STOLU:
        raise ValueError('Nieznane stanowisko albo stanowisko bez stołu: %r' % (kod,))
    dane = _dane_stanowiska(kod)
    kandydaci = dane['kandydaci']
    if dane['jednostka'] == 'zamowienie':
        kafle = [_kafel_zamowienia(dane, order_id) for order_id in kandydaci.kafle[:limit]]
    else:
        kafle = [_kafel_pozycji(dane, product_id) for product_id in kandydaci.kafle[:limit]]
    return {'stanowisko': kod, 'nazwa': station_label(kod), 'jednostka': dane['jednostka'],
            'lacznie': len(kandydaci.kafle), 'kafle': kafle,
            'niekompletne': [_niekompletne(dane, wiersz) for wiersz in kandydaci.niekompletne[:limit]]}


def _kto(user_id, worker_id, uzytkownicy, pracownicy):
    if user_id is not None and user_id in uzytkownicy:
        return uzytkownicy[user_id]
    if worker_id is not None and worker_id in pracownicy:
        return pracownicy[worker_id]
    return None


def _nazwy_osob(user_ids, worker_ids):
    """Imiona i nazwiska użytkowników panelu i pracowników — dwa zapytania na całą listę."""
    from modules.users.models import User
    uzytkownicy, pracownicy = {}, {}
    user_ids = sorted({i for i in user_ids if i is not None})
    worker_ids = sorted({i for i in worker_ids if i is not None})
    if user_ids:
        for uzytkownik in (db.session.query(User.id, User.first_name, User.last_name)
                           .filter(User.id.in_(user_ids)).all()):
            nazwa = u' '.join(c for c in (uzytkownik.first_name, uzytkownik.last_name) if c).strip()
            uzytkownicy[uzytkownik.id] = nazwa or None
    if worker_ids:
        for pracownik in (db.session.query(ProductionWorker.id, ProductionWorker.first_name,
                                           ProductionWorker.last_name)
                          .filter(ProductionWorker.id.in_(worker_ids)).all()):
            nazwa = u' '.join(c for c in (pracownik.first_name, pracownik.last_name) if c).strip()
            pracownicy[pracownik.id] = nazwa or None
    return uzytkownicy, pracownicy


def _krotkie_nazwy_pracownikow(worker_ids):
    """{id pracownika: „Adam K.”} — pracownik na ekranach hali (monitor; spec 6.1, 7.2). Jedno zapytanie, tylko gdy
    są id. Formatuje `stol.imie_z_inicjalem` (to samo co tablet)."""
    from modules.production.priorytety.services import stol   # import lokalny: `stol` importuje ten moduł
    worker_ids = sorted({i for i in worker_ids if i is not None})
    if not worker_ids:
        return {}
    return {pracownik.id: stol.imie_z_inicjalem(pracownik.first_name, pracownik.last_name)
            for pracownik in (db.session.query(ProductionWorker.id, ProductionWorker.first_name,
                                               ProductionWorker.last_name)
                              .filter(ProductionWorker.id.in_(worker_ids)).all())}


def _w_kolejce(dane, stanowisko, order_id):
    """Miejsce zamówienia w kolejce stanowiska (pierwszy jego kafel) albo None (na stole, niekompletne). Pakowanie
    bez sposobu dostawy ma miejsce jak każde inne (logistyka 4.6, spec 5.1)."""
    kafle = dane['kandydaci'].kafle
    if dane['jednostka'] == 'zamowienie':
        zamowienia_kafli = kafle
    else:
        zamowienia_kafli = [dane['pozycje_stanowiska'][product_id].order_id for product_id in kafle]
    if order_id not in zamowienia_kafli:
        return None
    return {'miejsce': zamowienia_kafli.index(order_id) + 1, 'z': len(zamowienia_kafli)}


def _stanowisko_zamowienia(stanowisko, zamowienie, pozycje, nazwy):
    status = STATION_PENDING_STATUS[stanowisko]
    if stanowisko in ustawienia.STANOWISKA_BEZ_STOLU:
        # Lakiernia nie ma stołu (spec, ustalenie 15): pracuje z listy ułożonej po wykończeniu, więc algorytm stołu
        # nie wyznacza tu miejsca w kolejce. Miejsce na liście Lakierni dołoży krok, który ją zbuduje.
        return {'stanowisko': stanowisko, 'nazwa': station_label(stanowisko),
                'pozycji': sum(1 for pozycja in pozycje if pozycja.current_status == status),
                'na_stole': [], 'odlozone': [], 'w_kolejce': None, 'niekompletne': False}
    dane = _dane_stanowiska(stanowisko)
    prefiks = _prefiks_jednostki(dane['jednostka'])
    short = {pozycja.id: pozycja.short_product_id for pozycja in pozycje}
    na_stole, odlozone = [], []
    for wiersz in dane['stol']:
        if wiersz.order_id != zamowienie.id or not wiersz.unit_key.startswith(prefiks):
            continue
        oznaczenie = short.get(wiersz.product_id) if wiersz.product_id else zamowienie.internal_order_number
        if wiersz.postponed_at is None:
            na_stole.append(oznaczenie)
        else:
            odlozone.append({'short_id': short.get(wiersz.product_id) if wiersz.product_id else None,
                             'powod': wiersz.postpone_reason, 'notatka': wiersz.postpone_note,
                             'kiedy': _czas(wiersz.postponed_at),
                             'pracownik': nazwy.get(wiersz.postponed_by_worker_id)})
    return {
        'stanowisko': stanowisko,
        'nazwa': station_label(stanowisko),
        'pozycji': sum(1 for pozycja in pozycje if pozycja.current_status == status),
        'na_stole': na_stole,
        'odlozone': odlozone,
        'w_kolejce': _w_kolejce(dane, stanowisko, zamowienie.id),
        'niekompletne': any(wiersz[0] == zamowienie.id for wiersz in dane['kandydaci'].niekompletne),
    }


def _czas(wartosc):
    return wartosc.isoformat() if wartosc is not None else None


def priorytet_zamowienia(order_id):
    """
    Dane modalu priorytetu zamówienia (spec 7.1): gwiazdki z autorem zmiany, szczebel („szczebel 2 z 11”), ranga,
    tagi i termin liczone na żywo, trasa, gdzie leży na każdym stanowisku (stół, odłożone, miejsce w kolejce,
    niekompletne) i ostatnie wpisy logu. None, gdy zamówienia nie ma. Same zwykłe odczyty.
    """
    zamowienie = (ProductionOrder.query
                  .options(load_only(ProductionOrder.id, ProductionOrder.internal_order_number,
                                     ProductionOrder.client_name, ProductionOrder.priority_stars,
                                     ProductionOrder.priority_stars_set_at, ProductionOrder.priority_stars_set_by),
                           selectinload(ProductionOrder.products).load_only(*_KOLUMNY_POZYCJI))
                  .filter(ProductionOrder.id == order_id).first())
    if zamowienie is None:
        return None
    pozycje = sorted(zamowienie.products, key=lambda p: p.id)
    widoczne, po_kluczu, migawka, wynik = _na_zywo()
    nazwy_tras = {route_id: trasa.name for route_id, trasa in migawka.trasy.items()}
    ranga = wynik.zamowienia.get(order_id)

    historia = (PriorityLog.query.filter(PriorityLog.order_id == order_id)
                .order_by(PriorityLog.created_at.desc(), PriorityLog.id.desc()).limit(LIMIT_HISTORII).all())
    stanowiska = [kod for kod in STATION_ORDER
                  if any(p.current_status == STATION_PENDING_STATUS[kod] for p in pozycje)] if ranga else []
    odlozenia = (db.session.query(StationDesk.postponed_by_worker_id)
                 .filter(StationDesk.order_id == order_id, StationDesk.postponed_at.isnot(None)).all())
    uzytkownicy, pracownicy = _nazwy_osob(
        [w.user_id for w in historia] + [zamowienie.priority_stars_set_by],
        [w.worker_id for w in historia] + [w[0] for w in odlozenia])

    szczebel = None
    if ranga is not None:
        wiersz = _wiersz_kolejki(order_id, ranga, migawka, wynik, po_kluczu, nazwy_tras)
        szczebel = dict(wiersz['szczebel'], z=len(widoczne))
    gwiazdki_ustawione = None
    if zamowienie.priority_stars_set_at is not None:
        gwiazdki_ustawione = {'kiedy': _czas(zamowienie.priority_stars_set_at),
                              'kto': uzytkownicy.get(zamowienie.priority_stars_set_by)}
    route_id = migawka.trasa_zamowienia.get(order_id)
    return {
        'zamowienie': {'order_id': zamowienie.id, 'numer': zamowienie.internal_order_number,
                       'klient': zamowienie.client_name},
        'gwiazdki': int(zamowienie.priority_stars or 0),
        'gwiazdki_ustawione': gwiazdki_ustawione,
        'aktywne': ranga is not None,
        'ranga': ranga.rank if ranga is not None else None,
        'szczebel': szczebel,
        'tagi': list(ranga.tagi) if ranga is not None else [],
        'termin': _data(ranga.termin if ranga is not None else kolejka.termin_zamowienia(pozycje)),
        'trasa': _trasa_krotka(migawka.trasy.get(route_id)) if route_id is not None else None,
        'stanowiska': [_stanowisko_zamowienia(kod, zamowienie, pozycje, pracownicy) for kod in stanowiska],
        'historia': [{'akcja': w.action, 'stare': w.old_value, 'nowe': w.new_value, 'powod': w.reason,
                      'notatka': w.note, 'stanowisko': w.station_code, 'kiedy': _czas(w.created_at),
                      'kto': _kto(w.user_id, w.worker_id, uzytkownicy, pracownicy)} for w in historia],
    }


# ── stoły i odłożenia dla panelu (krok K3; spec 5.3, 7.2) ───────────────────────────────────────────────────
# Zakładka Stanowiska i modale Listy produkcyjnej pokazują to samo, co widzi tablet: stół i odłożone każdego
# stanowiska ze stołem (bez Lakierni — spec, ustalenie 15). Same ZWYKŁE odczyty: bez blokad, bez zapisów i BEZ
# dopełniania stołu (dopełnia wyłącznie `GET desk` tabletu).

def _kolejka_dalej(dane, kod):
    """Ile kafli czeka w kolejce stanowiska poza stołem i odłożonymi — ta sama liczba co `kolejka_dalej` na
    tablecie (`stol.stan`): wszyscy kandydaci, na Pakowaniu także zamówienia bez sposobu dostawy (logistyka 4.6)."""
    return len(dane['kandydaci'].kafle)


OPIS_WIDMA_POZYCJI = u'pozycja już nie czeka na stanowisku'
OPIS_WIDMA_ZAMOWIENIA = u'zamówienie bez pozycji na stanowisku'
OPIS_WIDMA_JEDNOSTKI = u'kafel innej jednostki (po zmianie ustawień)'


def _wroci_po_zdjeciu(dane, kod, kandydaci_pelne):
    """
    Funkcja `id kafla → bool`: czy kafel zdjęty ze stołu wróci przy najbliższym dopełnieniu — stanąłby w kolejce
    PRZED dzisiejszym pierwszym kandydatem (raport K3, D7: „Zdejmij” takiego kafla jest pozorne). `kandydaci_pelne` —
    kolejność kandydatów liczona bez ukrywania stołu (czysta funkcja, bez zapytań). Pakowanie bez sposobu dostawy
    wraca jak każdy kafel (logistyka 4.6, spec 5.1).
    """
    miejsce = {kafel_id: i for i, kafel_id in enumerate(kandydaci_pelne.kafle)}
    obecni = dane['kandydaci'].kafle
    pierwszy = miejsce.get(obecni[0]) if obecni else None

    def wroci(kafel_id):
        if kafel_id not in miejsce:
            return False
        return pierwszy is None or miejsce[kafel_id] < pierwszy
    return wroci


def _widma(wiersze, opisy):
    """Wiersze stołu, których nie pokazuje ani `stol`, ani `odlozone` (raport K3, D2): liczą się do K albo do limitu
    odłożeń, a biuro musi móc je zdjąć. Numer i `short_id` dwoma zapytaniami — tylko gdy widma są."""
    if not wiersze:
        return []
    numery = dict(db.session.query(ProductionOrder.id, ProductionOrder.internal_order_number)
                  .filter(ProductionOrder.id.in_(sorted({w.order_id for w in wiersze}))).all())
    id_pozycji = sorted({w.product_id for w in wiersze if w.product_id is not None})
    krotkie = {}
    if id_pozycji:
        krotkie = dict(db.session.query(ProductionProduct.id, ProductionProduct.short_product_id)
                       .filter(ProductionProduct.id.in_(id_pozycji)).all())
    return [{'unit_key': w.unit_key, 'order_id': w.order_id, 'numer': numery.get(w.order_id),
             'product_id': w.product_id, 'short_id': krotkie.get(w.product_id) if w.product_id else None,
             'zrodlo': w.zrodlo, 'pobrano': _czas(w.pulled_at), 'odlozony': w.postponed_at is not None,
             'opis': opisy[w.id]} for w in wiersze]


def _stol_stanowiska(kod):
    """Wiersz `GET /stoly` jednego stanowiska: ustawienia, stół i odłożone w kolejności tabletu, licznik kolejki,
    widma (wiersze stołu bez kafla do pokazania)."""
    from modules.production.priorytety.services import stol   # import lokalny: `stol` importuje ten moduł
    dane = _dane_stanowiska(kod)
    # Kafle ze stołu nie są kandydatami, więc `dane['pozycje_stanowiska']` ich nie ma — do opisu kafli budujemy
    # wejście jeszcze raz, bez ukrywania stołu (czysta funkcja, zero zapytań).
    wszystkie, statusy = wejscie_kandydatow(kod, list(dane['zamowienia'].values()), list(dane['pozycje'].values()),
                                            dane['trasa_zamowienia'], set())
    pelne = dict(dane, pozycje_stanowiska={pozycja.id: pozycja for pozycja in wszystkie})
    # Te same wejścia co `_dane_stanowiska` i `stol.dopelnij` — także pozycje omijające stanowisko, inaczej zamówienie
    # z pozycją bez docięcia wyglądałoby na niekompletne i podpis „wróci” by nie powstał (przegląd K4b, W1).
    kandydaci_pelne = kolejka.kandydaci_stanowiska(kod, wszystkie, statusy,
                                                   szczebel_rozpoczete=dane['szczebel_rozpoczete'],
                                                   jednostka=dane['jednostka'], omijajace=dane['omijajace'])
    wroci = _wroci_po_zdjeciu(dane, kod, kandydaci_pelne)
    prefiks = _prefiks_jednostki(dane['jednostka'])
    wiersze = stol.uporzadkuj(dane['stol'])
    uzytkownicy, pracownicy = _nazwy_osob([w.sent_by_user_id for w in wiersze],
                                          [w.postponed_by_worker_id for w in wiersze])
    krotkie = _krotkie_nazwy_pracownikow([w.postponed_by_worker_id for w in wiersze if w.postponed_at is not None])
    na_stole, odlozone, widma, opisy_widm = [], [], [], {}
    for wiersz in wiersze:
        if not wiersz.unit_key.startswith(prefiks):
            widma.append(wiersz)
            opisy_widm[wiersz.id] = OPIS_WIDMA_JEDNOSTKI
            continue
        if wiersz.product_id is not None:
            if wiersz.product_id not in pelne['pozycje_stanowiska']:
                # kafel pozycji, która już nie czeka na stanowisku — zdejmie go pierwszy pisarz albo biuro
                widma.append(wiersz)
                opisy_widm[wiersz.id] = OPIS_WIDMA_POZYCJI
                continue
            kafel = _kafel_pozycji(pelne, wiersz.product_id)
            kafel['wroci_przy_dopelnieniu'] = bool(kafel['dorobka'] or wroci(wiersz.product_id))
        else:
            if wiersz.order_id not in dane['zamowienia']:
                widma.append(wiersz)
                opisy_widm[wiersz.id] = OPIS_WIDMA_ZAMOWIENIA
                continue
            kafel = _kafel_zamowienia(dane, wiersz.order_id)
            kafel['wroci_przy_dopelnieniu'] = bool(wiersz.zrodlo == stale.ZRODLO_DOROBKA or wroci(wiersz.order_id))
        kafel.update({'unit_key': wiersz.unit_key, 'pobrano': _czas(wiersz.pulled_at), 'zrodlo': wiersz.zrodlo,
                      'wyslal': uzytkownicy.get(wiersz.sent_by_user_id)})
        if wiersz.postponed_at is None:
            na_stole.append(kafel)
        else:
            kafel.update({'powod': wiersz.postpone_reason,
                          'powod_etykieta': stale.ETYKIETY_POWODOW_ODLOZENIA.get(wiersz.postpone_reason,
                                                                                 wiersz.postpone_reason),
                          'notatka': wiersz.postpone_note,
                          'odlozono': _czas(wiersz.postponed_at),
                          'pracownik': pracownicy.get(wiersz.postponed_by_worker_id),
                          # „Adam K.” dla hali (monitor); pełne imię i nazwisko zostaje w `pracownik` dla panelu
                          'pracownik_krotko': krotkie.get(wiersz.postponed_by_worker_id)})
            odlozone.append(kafel)
    return {
        'stanowisko': kod, 'nazwa': station_label(kod), 'tryb': ustawienia.tryb(kod),
        'jednostka': dane['jednostka'], 'miejsca': ustawienia.miejsca(kod), 'limit_odlozen': ustawienia.limit(kod),
        'stol': na_stole, 'odlozone': odlozone, 'kolejka_dalej': _kolejka_dalej(dane, kod),
        'widma': _widma(widma, opisy_widm),
    }


def stanowiska_ze_stolem():
    """Kody stanowisk, które mają stół, w kolejności procesu (wszystkie poza Lakiernią)."""
    return [kod for kod in STATION_ORDER if kod not in ustawienia.STANOWISKA_BEZ_STOLU]


def stoly_panelu(stanowiska=None):
    """
    Stół i odłożone każdego stanowiska ze stołem (spec 7.2 — to samo, co widzi tablet, ze źródłem kafla):
    lista `{"stanowisko", "nazwa", "tryb", "jednostka", "miejsca", "limit_odlozen", "stol", "odlozone",
    "kolejka_dalej"}` w kolejności procesu. Kafel = kształt kafla z podglądu kolejki (`kolejka_stanowiska`) plus
    `unit_key`, `pobrano`, `zrodlo`, `wyslal`; odłożony dodatkowo `powod`, `powod_etykieta`, `notatka`, `odlozono`,
    `pracownik`.

    `stanowiska` — opcjonalny filtr kodów (monitor hali czyta jedno stanowisko); None = wszystkie ze stołem.
    Stanowisko bez stołu (Lakiernia) w filtrze nic nie daje.
    """
    kody = stanowiska_ze_stolem()
    if stanowiska is not None:
        wybrane = set(stanowiska)
        kody = [kod for kod in kody if kod in wybrane]
    return [_stol_stanowiska(kod) for kod in kody]


def odlozenia_panelu():
    """
    Otwarte odłożenia wszystkich stanowisk, najdłużej leżące pierwsze (spec 5.3 — plakietka „Odłożone na
    Sklejaniu: brak materiału, 9:40, Adam” i lista w modalu). Tylko kafle w bieżącej jednostce stanowiska.
    """
    wiersze = (StationDesk.query.filter(StationDesk.postponed_at.isnot(None))
               .order_by(StationDesk.postponed_at, StationDesk.id).all())
    prefiksy = {kod: _prefiks_jednostki(ustawienia.jednostka(kod)) for kod in stanowiska_ze_stolem()}
    wiersze = [w for w in wiersze if w.station_code in prefiksy and w.unit_key.startswith(prefiksy[w.station_code])]
    if not wiersze:
        return []
    numery = dict(db.session.query(ProductionOrder.id, ProductionOrder.internal_order_number)
                  .filter(ProductionOrder.id.in_(sorted({w.order_id for w in wiersze}))).all())
    id_pozycji = sorted({w.product_id for w in wiersze if w.product_id is not None})
    krotkie = {}
    if id_pozycji:
        krotkie = dict(db.session.query(ProductionProduct.id, ProductionProduct.short_product_id)
                       .filter(ProductionProduct.id.in_(id_pozycji)).all())
    _uzytkownicy, pracownicy = _nazwy_osob([], [w.postponed_by_worker_id for w in wiersze])
    return [{
        'stanowisko': w.station_code, 'nazwa': station_label(w.station_code), 'unit_key': w.unit_key,
        'order_id': w.order_id, 'numer': numery.get(w.order_id), 'product_id': w.product_id,
        'short_id': krotkie.get(w.product_id) if w.product_id is not None else None,
        'powod': w.postpone_reason, 'notatka': w.postpone_note, 'odlozono': _czas(w.postponed_at),
        'pracownik': pracownicy.get(w.postponed_by_worker_id),
    } for w in wiersze]
