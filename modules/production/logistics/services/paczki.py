# -*- coding: utf-8 -*-
"""
Paczki zamówienia (logistyka etap 4, krok 4.2, spec 5.2 i 7).

Paczka = paczka albo paleta zadeklarowana przy pakowaniu; kod na etykiecie i w QR to
'P-<id>'. Aktualna deklaracja zamówienia = jego paczki z voided_at IS NULL. Funkcje
NIE commitują — robi to wołający (API mobilne przez @with_idempotency).
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import insert

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import sposoby
from modules.production.logistics.services import delivery, paczki_druk
from modules.production.models import (
    LabelPrintJob, ProductionConfig, ProductionPackage, ProductionProduct, get_local_now,
)

logger = get_structured_logger('production.logistics.paczki')

# Stanowiska, które deklarują paczki i drukują ich etykiety (spec 6.1) — niezależnie od
# LABEL_PRINTER_ALLOWED_STATIONS (etykiety produktów). 'verification' dochodzi w kroku 4.3.
STANOWISKA_PACZEK = ('packaging', 'verification')
MAKS_PACZEK = 10
WYMIAR_EUR = (120, 80)
WYMIAR_MIN_CM, WYMIAR_MAX_CM = 20, 400
# Klucz wiersza prod_config, który serializuje deklaracje paczek — patrz zablokuj_deklaracje().
KLUCZ_BLOKADY = 'logistyka_paczki_blokada'
OPIS_BLOKADY = 'Logistyka: blokada deklaracji paczek (jedna naraz)'   # jak w migracji 2026-09-30
# Ostrzeżenie o braku wiersza blokady najwyżej raz na proces (jak routes._blokada_ostrzezono).
_blokada_ostrzezono = False


class PaczkiBlad(Exception):
    """Odmowa z kodem dla appki (`error`) i komunikatem dla człowieka (`message`)."""

    def __init__(self, kod, komunikat, status):
        super().__init__(komunikat)
        self.kod = kod
        self.komunikat = komunikat
        self.status = status


@dataclass(frozen=True)
class Deklaracja:
    kind: str
    count: int
    pallet_type: Optional[str] = None
    length_cm: Optional[int] = None
    width_cm: Optional[int] = None


def podpowiedz_pakowania(produkty):
    """
    Obiekt `packing_hint` (spec 7.1) z pozycji JEDNEGO zamówienia: szacunek wagi
    (Σ objętość × sztuki niezanulowanych pozycji × WAGA_KG_NA_M3), powyżej
    PROG_PALETY_KG paleta EUR ×1, do progu paczka ×1. Waga zaokrąglona do kilograma
    i porównywana po zaokrągleniu — próg ma działać tak, jak liczba widziana na tablecie.
    """
    m3 = sum(float(p.volume_m3 or 0) * (p.quantity or 1)
             for p in produkty if p.current_status != 'anulowane')
    waga = int(round(m3 * sposoby.WAGA_KG_NA_M3))
    if waga > sposoby.PROG_PALETY_KG:
        return {'kind': 'paleta', 'count': 1, 'pallet_type': 'eur', 'weight_kg': waga}
    return {'kind': 'paczka', 'count': 1, 'pallet_type': None, 'weight_kg': waga}


def podpowiedzi_zamowien(pozycje):
    """
    {order_id: packing_hint} z listy pozycji, w której są WSZYSTKIE pozycje każdego
    zamówienia — tak budują ją kolejka stanowiska i wyszukiwarka API mobilnego, więc
    mapa nie kosztuje ani jednego zapytania.
    """
    grupy = {}
    for p in pozycje:
        grupy.setdefault(p.order_id, []).append(p)
    return {order_id: podpowiedz_pakowania(produkty) for order_id, produkty in grupy.items()}


def aktualne_paczki(order_id, do_zapisu=False):
    """
    Paczki aktualnej deklaracji w kolejności numerów. `do_zapisu=True` — odczyt bieżący
    z blokadą wierszy (FOR UPDATE): MySQL pracuje na REPEATABLE READ, więc zwykły SELECT
    po zablokowaniu zamówienia widziałby migawkę sprzed czekania na blokadę i przegapił
    paczki zadeklarowane w tym czasie przez inne urządzenie.
    """
    zapytanie = (ProductionPackage.query
                 .filter(ProductionPackage.order_id == order_id,
                         ProductionPackage.voided_at.is_(None))
                 .order_by(ProductionPackage.seq, ProductionPackage.id))
    if do_zapisu:
        zapytanie = zapytanie.with_for_update().populate_existing()
    return zapytanie.all()


def aktualne_paczki_zamowien(order_ids):
    """{order_id: [paczki aktualnej deklaracji]} jednym zapytaniem (listy panelu Logistyki)."""
    if not order_ids:
        return {}
    wynik = {}
    for p in (ProductionPackage.query
              .filter(ProductionPackage.order_id.in_(list(order_ids)),
                      ProductionPackage.voided_at.is_(None))
              .order_by(ProductionPackage.order_id, ProductionPackage.seq, ProductionPackage.id)):
        wynik.setdefault(p.order_id, []).append(p)
    return wynik


def zablokuj_stan(order):
    """
    Odczyt BIEŻĄCY stanu, na którym zapis paczek albo Weryfikacji ma zdecydować. Zwraca aktualne paczki
    zamówienia. Jedyna definicja tego odczytu: woła ją `zadeklaruj` (deklaracja paczek) i
    `weryfikacja.zablokuj_stan` (zapisy Weryfikacji), żeby obie strony decydowały na tym samym stanie.

    Kolejność blokad (każdy taki zapis): zamówienie FOR UPDATE trzyma już wołający (router) → paczki FOR
    UPDATE → pozycje FOR UPDATE po kluczu głównym (bez blokad luk) → dopiero zapisy. Odczyt jest BIEŻĄCY
    (`populate_existing`), nie zwykły: MySQL pracuje na REPEATABLE READ, a migawka powstaje przy pierwszym
    zwykłym odczycie transakcji (już w before_request albo przy sprawdzaniu pracownika), więc leniwe
    `order.products` pokazałoby statusy sprzed czekania na blokady — cudze przepakowanie, „Wydane
    klientowi”, anulowanie z synchronizacji, weryfikacja albo pierwszy z dwóch skanów zostałyby po cichu
    nadpisane albo strażnik (order_verified, order_not_packed) przepuściłby przegranego w wyścigu.
    `populate_existing` odświeża pozycje w identity map, więc `order.products`, `podbij_pozycje`
    i serializer odpowiedzi widzą bieżące wartości. Lista pozycji (klucze) pochodzi z `order.products`:
    blokada po `order_id` zakładałaby blokady luk na indeksie i zakleszczała się.
    """
    aktualne = aktualne_paczki(order.id, do_zapisu=True)
    ids = [p.id for p in order.products]
    if ids:
        (ProductionProduct.query.filter(ProductionProduct.id.in_(ids)).order_by(ProductionProduct.id)
         .with_for_update().populate_existing().all())
    return aktualne


def serializuj_paczke(p):
    """Paczka w API mobilnym (kontrakt kroków 4.2–4.3)."""
    return {
        'id': p.id,
        'code': p.kod,
        'seq': p.seq,
        'kind': p.kind,
        'pallet_type': p.pallet_type,
        'length_cm': p.length_cm,
        'width_cm': p.width_cm,
        'label_print_count': p.label_print_count or 0,
        'label_printed_at': p.label_printed_at.isoformat() if p.label_printed_at else None,
        # Krok 4.3: stan weryfikacji (telefon Weryfikacji, spec 8.2).
        'verified': p.verified_at is not None,
        'verified_at': p.verified_at.isoformat() if p.verified_at else None,
        'verified_method': p.verified_method,
    }


def _liczba(wartosc):
    """
    Liczba całkowita z JSON-a. Bool to nie liczba (w Pythonie True == 1); całkowity float
    (2.0) przyjmujemy jako 2, bo 422 jest zapamiętywane i wyrzuca deklarację z kolejki
    offline tabletu; 1.5 i tekst odpadają.
    """
    if isinstance(wartosc, bool):
        return None
    if isinstance(wartosc, int):
        return wartosc
    if isinstance(wartosc, float) and wartosc.is_integer():
        return int(wartosc)
    return None


def waliduj_deklaracje(dane):
    """
    Body PUT …/packages → Deklaracja albo PaczkiBlad 422 `invalid_packages`.

    Pola bez znaczenia dla danego rodzaju pomijamy zamiast odrzucać (wymiar przy EUR i przy
    paczce, typ palety przy paczce): 422 z kolejki offline tabletu to deklaracja utracona
    bez śladu, a te pola nie zmieniają jej sensu. EUR ma zawsze 120×80.
    """
    def blad(tekst):
        return PaczkiBlad('invalid_packages', tekst, 422)

    if not isinstance(dane, dict):
        raise blad(u'Brak danych paczek.')
    kind = dane.get('kind')
    if kind not in ProductionPackage.RODZAJE:
        raise blad(u'Rodzaj musi być „paczka” albo „paleta”.')
    count = _liczba(dane.get('count'))
    if count is None or not 1 <= count <= MAKS_PACZEK:
        raise blad(u'Liczba paczek od 1 do %d.' % MAKS_PACZEK)
    if kind == 'paczka':
        return Deklaracja('paczka', count)
    typ = dane.get('pallet_type')
    if typ == 'eur':
        return Deklaracja('paleta', count, 'eur', *WYMIAR_EUR)
    if typ == 'niestandardowa':
        dlugosc, szerokosc = _liczba(dane.get('length_cm')), _liczba(dane.get('width_cm'))
        if dlugosc is None or szerokosc is None or not all(
                WYMIAR_MIN_CM <= w <= WYMIAR_MAX_CM for w in (dlugosc, szerokosc)):
            raise blad(u'Wymiar palety niestandardowej: od %d do %d cm.' % (WYMIAR_MIN_CM, WYMIAR_MAX_CM))
        return Deklaracja('paleta', count, 'niestandardowa', dlugosc, szerokosc)
    raise blad(u'Typ palety: „eur” albo „niestandardowa”.')


def opis(kind, count, pallet_type=None, length_cm=None, width_cm=None):
    """„3 × paczka”, „1 × EUR”, „2 × paleta 150×100” — log logistyki i komunikaty (spec 11)."""
    if kind != 'paleta':
        rodzaj = u'paczka'
    elif pallet_type == 'eur':
        rodzaj = u'EUR'
    elif length_cm and width_cm:
        rodzaj = u'paleta %d×%d' % (length_cm, width_cm)
    else:
        rodzaj = u'paleta'
    return u'%d × %s' % (count, rodzaj)


def opis_paczek(lista):
    """Opis zapisanej deklaracji (jeden rodzaj na zamówienie — mieszane poza zakresem, spec 3)."""
    if not lista:
        return None
    p = lista[0]
    return opis(p.kind, len(lista), p.pallet_type, p.length_cm, p.width_cm)


def uniewaznij(lista, teraz, powod=u'nowa deklaracja paczek'):
    """
    Unieważnia paczki (wiersze zostają — skan starej etykiety ma dostać „nieaktualna”) i
    w tej samej transakcji wygasza ich oczekujące zadania druku (`pending` → `expired`).
    Agent druku pobiera właśnie `pending`, więc bez tego etykiety starych paczek wyszłyby
    na drukarkę obok nowych (np. po przerwie w pracy agenta). Zadań `printed` i `failed`
    nie ruszamy; zadanie już przekazane do spoolera Windows jest poza zasięgiem CRM.
    `powod` trafia do komunikatu wygaszonego zadania. Zwraca liczbę unieważnionych paczek.
    """
    for p in lista:
        p.voided_at = teraz
    if lista:
        (LabelPrintJob.query
         .filter(LabelPrintJob.status == LabelPrintJob.STATUS_PENDING,
                 LabelPrintJob.package_id.in_([p.id for p in lista]))
         .update({'status': LabelPrintJob.STATUS_EXPIRED,
                  'error_message': u'Paczka unieważniona — {}'.format(powod)},
                 synchronize_session=False))
    return len(lista)


def zablokuj_deklaracje():
    """
    Blokada „jedna deklaracja paczek naraz”: FOR UPDATE na wspólnym wierszu `prod_config`
    `logistyka_paczki_blokada` (zakłada go migracja 2026-09-30-logistyka-paczki-blokada.sql).
    Zwraca ten wiersz albo None, gdy go nie ma (baza bez migracji, SQLite testów).

    DLACZEGO: `zadeklaruj` czyta poprzednie paczki zamówienia odczytem blokującym
    (`aktualne_paczki(..., do_zapisu=True)`, czyli SELECT … FOR UPDATE po `order_id`). Gdy
    zamówienie nie ma jeszcze paczek, InnoDB bierze blokadę LUKI indeksu `ix_prod_packages_order_id`.
    Blokady luk są ze sobą zgodne, więc dwie pierwsze deklaracje dla RÓŻNYCH zamówień blokują
    tę samą lukę, po czym obie wstawiają nowe paczki w tę lukę — każda czeka na drugą i MySQL
    cofa jedną (1213). Zmierzone 30.09 na kopii produkcji: 4 zakleszczenia w 5 próbach.
    Deklaracje są rzadkie (jedna na spakowane zamówienie), więc serializujemy je jednym wierszem
    blokady, tak jak zapisy tras (`routes.zablokuj_trasy`).

    ZASADA KOLEJNOŚCI BLOKAD (ta sama transakcja, od początku): pracownicy (touch_sessions w
    `_resolve_workers`) → `zablokuj_deklaracje()` → wiersz zamówienia po PK → paczki. Nikt
    inny nie bierze tej blokady. Ponowny druk (`order_packages_print`, `package_print`) jej nie
    potrzebuje: nie wstawia paczek, więc jego blokady rekordów i luk nie tworzą cyklu z deklaracją.

    Brak wiersza: na MySQL zakładamy go sami w TEJ transakcji (`INSERT IGNORE`, potem ponowny
    odczyt FOR UPDATE, WARNING w logu) — baza, która wykonała migrację przed dodaniem tego
    wiersza, nie zostanie z wyścigiem. Na innych bazach (SQLite testów: fixture tworzy sam
    schemat) deklaracje nie są serializowane, a ostrzeżenie idzie raz na proces (fail-open).
    """
    global _blokada_ostrzezono
    zapytanie = ProductionConfig.query.filter_by(config_key=KLUCZ_BLOKADY).with_for_update()
    wiersz = zapytanie.first()
    if wiersz is None and _samonaprawa_blokady():
        _zaloz_wiersz_blokady()
        wiersz = zapytanie.populate_existing().first()
        logger.warning(u"Brak wiersza blokady paczek '{}' w prod_config - zalozony "
                       u"(INSERT IGNORE); od teraz deklaracje paczek sa serializowane".format(KLUCZ_BLOKADY))
    if wiersz is None and not _blokada_ostrzezono:
        _blokada_ostrzezono = True
        logger.warning(u"Brak wiersza blokady paczek '{}' w prod_config - deklaracje paczek "
                       u"NIE sa serializowane (migracja go zaklada)".format(KLUCZ_BLOKADY))
    return wiersz


def _samonaprawa_blokady():
    """Samonaprawa brakującego wiersza blokady tylko na MySQL (produkcja, lokalny Docker)."""
    return db.engine.dialect.name == 'mysql'


def _zaloz_wiersz_blokady():
    """
    Wiersz blokady jak w migracji — INSERT IGNORE w bieżącej transakcji (nie w osobnym
    połączeniu: SELECT … FOR UPDATE, który nie znalazł wiersza, trzyma blokadę luki indeksu
    config_key, więc wstawienie z innej transakcji czekałoby na nas). Przefiks „OR IGNORE”
    dla SQLite — tylko dla testu samonaprawy.
    """
    teraz = get_local_now()
    db.session.execute(
        insert(ProductionConfig.__table__)
        .prefix_with('IGNORE', dialect='mysql')
        .prefix_with('OR IGNORE', dialect='sqlite')
        .values(config_key=KLUCZ_BLOKADY, config_value='', config_description=OPIS_BLOKADY,
                config_type='string', created_at=teraz, updated_at=teraz))


# Spec 7.2 i 13: deklaracja po weryfikacji → 409 order_verified (najpierw „Cofnij weryfikację”).
_ODMOWA_PO_WERYFIKACJI = {
    'zweryfikowane': u'Zamówienie {} jest już zweryfikowane — najpierw „Cofnij weryfikację”, potem '
                     u'zadeklaruj paczki od nowa.',
    'zaladowane': u'Zamówienie {} jest już załadowane — paczek nie można zmienić.',
    'dostarczone': u'Zamówienie {} jest już dostarczone — paczek nie można zmienić.',
}


_ODMOWA_NIESPAKOWANE = (u'Zamówienie {} nie jest jeszcze w całości spakowane — '
                        u'paczki deklaruje się po spakowaniu ostatniej pozycji.')


def _sprawdz_zakres_telefonu(order, stanowisko, teraz):
    """Deklaracja z telefonu Weryfikacji tylko w zakresie listy: poza nim 409 order_status (ten sam kod i
    komunikat co zapisy Weryfikacji). Tablet pakowania nie ma tego ograniczenia."""
    from modules.production.logistics.services import weryfikacja
    if stanowisko != weryfikacja.STANOWISKO:
        return
    try:
        weryfikacja.sprawdz_zakres(order, teraz)
    except weryfikacja.WeryfikacjaBlad as e:
        raise PaczkiBlad(e.kod, e.komunikat, e.status)


def zadeklaruj(order, deklaracja, stanowisko, aktor, worker_id=None, device_id=None, teraz=None):
    """
    Nowa deklaracja paczek (spec 7.2): unieważnia poprzednią, tworzy N paczek z numerami
    1..N, zapisuje log `paczki`, podbija ETag kolejek tabletów i kolejkuje N etykiet na
    drukarkę 'wysylka'. NIE commituje. Zwraca krotkę (nowe paczki, liczba unieważnionych).

    Router bierze najpierw `zablokuj_deklaracje()` (kolejność blokad: patrz jej docstring).
    `order` MUSI być odczytany z blokadą i `populate_existing` (_zamowienie_po_numerze(do_zapisu=True)) —
    dwie deklaracje naraz (dwa tablety, powtórka z nowym X-Operation-Id) dałyby dwa komplety paczek.

    KOLEJNOŚĆ SPRAWDZEŃ (trzy kroki):
    1. WSTĘPNA ODMOWA `order_not_packed` na stanie z pamięci (migawka MySQL, REPEATABLE READ), zanim
       cokolwiek zablokujemy. Migawka pokazuje tylko zatwierdzone zmiany: jeśli widać w niej, że
       wszystkie pozycje są spakowane lub dalej, ostatni „ZAKOŃCZ” już się zatwierdził i nie trzyma
       pozycji. Jeśli nie widać, odmawiamy od razu, bez sięgania po pozycje. Czekanie na nie pod blokadą
       zamówienia zakleszczało się z „ZAKOŃCZ” (MySQL 1213): ostatni „ZAKOŃCZ” trzyma pozycję i sięga po
       zamówienie, a deklaracja trzyma zamówienie i sięgałaby po pozycję. 409 jest w BLEDY_DO_PONOWIENIA,
       więc appka ponowi tą samą operację, gdy „ZAKOŃCZ” się zatwierdzi.
    2. ODCZYT BIEŻĄCY (`zablokuj_stan`: paczki FOR UPDATE → pozycje po PK FOR UPDATE z `populate_existing`,
       ta sama kolejność i ten sam odczyt co zapisy Weryfikacji).
    3. OBA STRAŻNIKI (order_verified, order_not_packed) na statusach z tego odczytu: ostateczna decyzja
       zapada na stanie bieżącym, więc przegrany w wyścigu z weryfikacją (która zdążyła po migawce) dostaje
       409 order_verified zamiast deklarować nowe paczki po weryfikacji (zamówienie zweryfikowane z
       niesprawdzonymi aktualnymi paczkami).
    Migawka nadal ma wpływ w jednym miejscu: LISTA kluczy pozycji do zablokowania pochodzi z
    `order.products` (blokada po `order_id` zakładałaby blokady luk indeksu i zakleszczała się). Pozycja
    dodana przez synchronizację po migawce nie jest więc ani blokowana, ani widziana przez strażniki; jeśli
    przez nią zamówienie przestało być w całości spakowane, trafi do reguły uniewaznij_etapy w cronie,
    który unieważni paczki.
    Przy wyścigu ze zmianą sposobu dostawy w panelu napis na etykiecie czytamy z zablokowanego wiersza
    zamówienia; przepakowanie i tak kończy się nową deklaracją, a zamówienie, które przestało być w
    całości spakowane, traci paczki przez weryfikacja.uniewaznij_etapy.

    Telefon Weryfikacji (stanowisko 'verification') deklaruje tylko na zamówieniach z zakresu listy
    (weryfikacja.sprawdz_zakres, po strażnikach, przed pierwszym zapisem). Tablet pakowania bez zmian.
    """
    if not delivery.wszystkie_w(order, sposoby.STATUSY_PO_SPAKOWANIU):
        raise PaczkiBlad('order_not_packed', _ODMOWA_NIESPAKOWANE.format(order.internal_order_number), 409)
    stare = zablokuj_stan(order)
    etap = next((p.current_status for p in delivery.aktywne_produkty(order)
                 if p.current_status in sposoby.STATUSY_LOGISTYCZNE), None)
    if etap is not None:
        raise PaczkiBlad('order_verified', _ODMOWA_PO_WERYFIKACJI[etap].format(
            order.internal_order_number), 409)
    if not delivery.wszystkie_w(order, ('spakowane',)):
        raise PaczkiBlad('order_not_packed', _ODMOWA_NIESPAKOWANE.format(order.internal_order_number), 409)
    teraz = teraz or get_local_now()
    _sprawdz_zakres_telefonu(order, stanowisko, teraz)
    uniewaznione = uniewaznij(stare, teraz)
    nowe = [ProductionPackage(order_id=order.id, seq=numer, kind=deklaracja.kind,
                              pallet_type=deklaracja.pallet_type, length_cm=deklaracja.length_cm,
                              width_cm=deklaracja.width_cm, declared_at=teraz,
                              declared_by_worker_id=worker_id, declared_device_id=device_id)
            for numer in range(1, deklaracja.count + 1)]
    db.session.add_all(nowe)
    db.session.flush()
    order.packages_declared_at = teraz
    delivery.zapisz_log(order, 'paczki', opis_paczek(stare),
                        opis(deklaracja.kind, deklaracja.count, deklaracja.pallet_type,
                             deklaracja.length_cm, deklaracja.width_cm),
                        worker_id=worker_id, device_id=device_id,
                        note=u'stanowisko: {}'.format(stanowisko), teraz=teraz)
    # ETag kolejek tabletów liczy się z MAX(updated_at) pozycji.
    delivery.podbij_pozycje(order, teraz)
    paczki_druk.drukuj_etykiety(order, nowe, len(nowe), stanowisko, aktor, teraz)
    return nowe, uniewaznione


def drukuj_ponownie_paczke(paczka, stanowisko, aktor, teraz=None):
    """
    Ponowny druk etykiety jednej ważnej paczki (spec 7.3) z BIEŻĄCYMI danymi zamówienia —
    gasi ikonę „etykiety paczek sprzed zmiany”. Paczka z unieważnionej deklaracji → 409.
    `paczka` MUSI być odczytana z blokadą (równoległa deklaracja mogła ją unieważnić).
    """
    if paczka.voided_at is not None:
        raise PaczkiBlad('package_void', u'Etykieta nieaktualna — paczki zadeklarowano ponownie.', 409)
    # Odczyt celowo bez blokady: rodzeństwo ważnej, zablokowanej paczki nie może się zmienić
    # (deklaracja unieważnia wszystkie naraz), a blokowanie rodzeństwa zakleszczyłoby dwa
    # równoległe przedruki pojedynczych paczek.
    z_ilu = len(aktualne_paczki(paczka.order_id))
    paczki_druk.drukuj_etykiety(paczka.order, [paczka], z_ilu, stanowisko, aktor,
                                teraz or get_local_now())


def drukuj_ponownie_zamowienie(order, stanowisko, aktor, teraz=None):
    """Ponowny druk etykiet wszystkich ważnych paczek zamówienia. Zwraca paczki; bez
    deklaracji → 409 no_packages. `order` z blokadą (jak w zadeklaruj)."""
    aktualne = aktualne_paczki(order.id, do_zapisu=True)
    if not aktualne:
        raise PaczkiBlad('no_packages', u'Zamówienie {} nie ma zadeklarowanych paczek.'.format(
            order.internal_order_number), 409)
    paczki_druk.drukuj_etykiety(order, aktualne, len(aktualne), stanowisko, aktor,
                                teraz or get_local_now())
    return aktualne
