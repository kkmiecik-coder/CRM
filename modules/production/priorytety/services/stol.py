# -*- coding: utf-8 -*-
"""
Stół stanowiska (spec 2026-10-04, sekcje 5.1–5.8, 9.2, 9.4): kafle, które tablety stanowiska pokazują jako „do
zrobienia” (wiersze `prod_station_desk` z `postponed_at` NULL) i kafle odłożone. Stan serwera, wspólny dla wszystkich
tabletów stanowiska.

Kafel to pozycja (`p:<product_id>`) albo całe zamówienie (`o:<order_id>`) — zależnie od jednostki stanowiska
(`ustawienia.jednostka`). Wiersz z kluczem innej jednostki niż bieżąca jest nieaktualny: nikogo nie ukrywa, nie
liczy się do miejsc, a pierwszy pisarz zamówienia go zdejmuje.

KOLEJNOŚĆ BLOKAD (spec 9.4; CLAUDE.md „zamówienie najpierw”). Wiersze stołu zapisują dwie grupy pisarzy:

1. Pisarze ZAMÓWIENIA — ZAKOŃCZ, Odłóż, hurtowa zmiana statusu, doróbka, zmiany z Base., cron osieroconych. Trzymają
   już blokadę X zamówienia i jego pozycji (services/blokady_zamowien.py) i dopiero pod nią dotykają wierszy stołu
   WŁASNEGO zamówienia:
       [blokada tras] → X zamówienie → X pozycje → zapisy pozycji
           → SELECT prod_station_desk WHERE station_code = ? AND unit_key = ? FOR UPDATE   (własny kafel: bramka, Odłóż)
           → SELECT prod_station_desk WHERE order_id = ? FOR UPDATE                        (`zdejmij_nieaktualne`)
           → UPDATE / DELETE wiersza
   Wiersz stołu to dziecko FK zamówienia już trzymanego X, więc nie dochodzi żadna nowa kolejność. Odczyty są
   BIEŻĄCE (`with_for_update().populate_existing()`): zwykły odczyt pokazałby na MySQL migawkę żądania, czyli stan
   sprzed kafla, który dopełnianie innego tabletu wstawiło i zatwierdziło chwilę wcześniej.

2. Pisarze STOŁU — dopełnianie (`GET desk`), „Wyślij na stanowisko”, „Zdejmij ze stołu”, start stołów. Biegną we
   własnym żądaniu, pod blokadą wiersza `prod_config` `priorytety_blokada_<S>` (jeden naraz na stanowisko), a
   zamówienia i pozycje czytają odczytem bieżącym WSPÓŁDZIELONYM (FOR SHARE), w kolejności kanonicznej: zamówienia
   rosnąco po id → pozycje. Nie biorą blokad X zamówień ani blokady tras.

Pisarz z grupy 1 nigdy nie bierze `priorytety_blokada_<S>`, więc nie czeka na dopełnianie; dopełnianie czeka
najwyżej do końca cudzego ZAKOŃCZ. NIKT nie blokuje wierszy stołu CAŁEGO stanowiska (`WHERE station_code = ? FOR
UPDATE`): taki skan bierze rekord indeksu wtórnego przed rekordem klucza głównego, a ZAKOŃCZ innego zamówienia,
który trzyma już rekord klucza głównego swojego wiersza, przy DELETE musi oznaczyć ten sam rekord indeksu wtórnego
— cykl (MySQL 1213), także między dwoma tabletami jednego stanowiska. Liczniki stanowiska (stół, odłożone) czyta się
zwykłym odczytem. Z tego samego powodu odczyt bieżący wierszy stołu idzie ZAWSZE równością po całym kluczu unikalnym
(`station_code = ? AND unit_key = ?`, jeden klucz na zapytanie — dostęp `const`) albo po `order_id` własnego
zamówienia: `unit_key IN (…)` MySQL potrafi wykonać skanem indeksu stanowiska lub całej tabeli i zablokować cudze
kafle (`_wiersze_do_zapisu`).

`GET desk` czeka na cudzą blokadę najwyżej kilka sekund (`krotkie_czekanie_na_blokady`): wołają go wszystkie
tablety, więc jedna długo trzymana blokada zamówienia nie może zatrzymać ich żądań na limicie serwera.

Funkcje nie commitują i nie wysyłają sygnałów — robi to router albo dekorator `with_idempotency` (po commicie).
Moduł nie importuje `mobile_api_service` (ten sięga po stół — cykl importów); mapy stanowisk bierze ze
`station_catalog`.
"""
import re
from collections import namedtuple
from contextlib import contextmanager

from sqlalchemy import func, insert
from sqlalchemy.orm import load_only
from sqlalchemy.orm.attributes import set_committed_value

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics.models import Route, RouteStop
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionOrder, ProductionProduct, get_local_now)
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog, StationDesk
from modules.production.priorytety.services import drabina, kolejka, ustawienia, widok
from modules.production.services.station_catalog import STATION_PENDING_STATUS, station_label

logger = get_structured_logger('production.priorytety.stol')

KAFEL_POZYCJA = 'p'
KAFEL_ZAMOWIENIE = 'o'

# Nazwy stanowisk w komunikatach dla ludzi: „nie leży na stole Sklejania”, „Na Sklejaniu leży 10 odłożonych…”.
_NAZWA_DOPELNIACZ = {
    'cutting': u'Wycinania', 'assembly': u'Składania', 'gluing': u'Sklejania', 'formatting': u'Formatowania',
    'edges': u'Krawędzi', 'painting': u'Lakierni', 'packaging': u'Pakowania',
}
_NAZWA_MIEJSCOWNIK = {
    'cutting': u'Wycinaniu', 'assembly': u'Składaniu', 'gluing': u'Sklejaniu', 'formatting': u'Formatowaniu',
    'edges': u'Krawędziach', 'painting': u'Lakierni', 'packaging': u'Pakowaniu',
}


class BladStolu(Exception):
    """Odmowa operacji na stole: `kod` (dla klienta API), `komunikat` po polsku, `status` HTTP."""

    def __init__(self, kod, komunikat, status):
        super(BladStolu, self).__init__(komunikat)
        self.kod = kod
        self.komunikat = komunikat
        self.status = status


# ── klucze kafli ────────────────────────────────────────────────────────────────────────────────────────────

def klucz_pozycji(product_id):
    return '%s:%d' % (KAFEL_POZYCJA, product_id)


def klucz_zamowienia(order_id):
    return '%s:%d' % (KAFEL_ZAMOWIENIE, order_id)


def unit_key(kafel):
    """Klucz wiersza stołu: `o:<order_id>` dla zamówienia, `p:<product_id>` dla pozycji."""
    if isinstance(kafel, ProductionOrder):
        return klucz_zamowienia(kafel.id)
    return klucz_pozycji(kafel.id)


def klucz_kafla(item, station_code, jednostka=None):
    """Klucz kafla, w którym pozycja `item` leży na stanowisku — wg bieżącej jednostki stanowiska."""
    if jednostka is None:
        jednostka = ustawienia.jednostka(station_code)
    if jednostka == 'zamowienie':
        return klucz_zamowienia(item.order_id)
    return klucz_pozycji(item.id)


def _numer(order):
    if order is None:
        return u'?'
    return order.internal_order_number or u'#%d' % order.id


def imie_z_inicjalem(imie, nazwisko):
    """
    Pracownik na ekranach hali — tablet (`desk`, „Odłożone”) i monitory: imię + inicjał nazwiska, „Adam K.”
    (spec 6.1, decyzja Konrada 5.10). Pełne imię i nazwisko pokazuje tylko panel biura. Samo imię → imię; samo
    nazwisko → inicjał; nic → None.
    """
    imie = (imie or u'').strip()
    nazwisko = (nazwisko or u'').strip()
    inicjal = nazwisko[0].upper() + u'.' if nazwisko else u''
    return u' '.join(czesc for czesc in (imie, inicjal) if czesc) or None


# ── reguły wspólne ──────────────────────────────────────────────────────────────────────────────────────────

def kompletne_na(order, station_code):
    """Czy zamówienie jest kompletne na stanowisku (spec 5.6 p. 2) — jedna reguła z kolejką i podglądem panelu:
    `kolejka.kompletne_na_stanowisku` na statusach pozycji z `order.products`, bez pozycji, których ścieżka omija
    stanowisko (`widok.sciezka_omija`)."""
    pozycje = list(order.products)
    return kolejka.kompletne_na_stanowisku(tuple(p.current_status for p in pozycje), station_code,
                                           omija=tuple(widok.sciezka_omija(p, station_code) for p in pozycje))


def stara_appka(device):
    """
    Czy tablet ma appkę sprzed stołów (spec 5.5): próg `priorytety_min_app_version_code` > 0 i kod wersji z ostatniego
    heartbeatu poniżej progu albo nieznany (tablet bez heartbeatu). Próg 0 = nie ma bramki wersji, każdy tablet jest
    traktowany jak nowy.
    """
    prog = ustawienia.min_app_version()
    if prog <= 0:
        return False
    kod = getattr(device, 'last_app_version_code', None)
    return kod is None or kod < prog


# ── odczyt i zdjęcie kafla (pisarze zamówienia) ─────────────────────────────────────────────────────────────

def kafel_pozycji(item, station_code, *, do_zapisu=False):
    """
    Wiersz stołu, w którym pozycja `item` leży na stanowisku (na stole albo odłożony), albo None.

    `do_zapisu=True` — odczyt BIEŻĄCY (`FOR UPDATE` + `populate_existing`) po (`station_code`, `unit_key`), czyli
    tylko wiersz własnego kafla. Wołać wyłącznie pod blokadą X zamówienia tej pozycji i PRZED pierwszą zmianą
    obiektów w sesji.
    """
    zapytanie = StationDesk.query.filter(StationDesk.station_code == station_code,
                                         StationDesk.unit_key == klucz_kafla(item, station_code))
    if do_zapisu:
        zapytanie = zapytanie.with_for_update().populate_existing()
    return zapytanie.first()


def _usun_wiersz(wiersz, teraz, zamkniecie_odlozenia, worker_id, device_id):
    """DELETE wiersza stołu; kafel odłożony zamykany przez ZAKOŃCZ zostawia w logu `odlozenie_zamkniete` (czas
    leżenia liczy raport z `old_value` = chwila odłożenia)."""
    if zamkniecie_odlozenia and wiersz.postponed_at is not None:
        db.session.add(PriorityLog(
            action='odlozenie_zamkniete', order_id=wiersz.order_id, product_id=wiersz.product_id,
            station_code=wiersz.station_code, old_value=wiersz.postponed_at.isoformat(timespec='seconds'),
            reason=wiersz.postpone_reason, note=wiersz.postpone_note, worker_id=worker_id, device_id=device_id,
            created_at=teraz))
    db.session.delete(wiersz)


def zdejmij_kafel(kafel, station_code, *, teraz=None, worker_id=None, device_id=None, zamkniecie_odlozenia=False):
    """
    Zdejmuje kafel (`ProductionProduct` → `p:`, `ProductionOrder` → `o:`) ze stołu stanowiska. Zwraca, czy coś
    usunęła. WARUNEK WSTĘPNY: wołający trzyma X na zamówieniu i jego pozycjach.
    """
    wiersz = (StationDesk.query
              .filter(StationDesk.station_code == station_code, StationDesk.unit_key == unit_key(kafel))
              .with_for_update().populate_existing().first())
    if wiersz is None:
        return False
    _usun_wiersz(wiersz, teraz or get_local_now(), zamkniecie_odlozenia, worker_id, device_id)
    return True


def _aktualny(wiersz, order, pozycje, jednostki):
    """Czy wiersz stołu zamówienia nadal odpowiada stanowi pozycji (reguła `zdejmij_nieaktualne`)."""
    stanowisko = wiersz.station_code
    if stanowisko not in STATION_PENDING_STATUS or stanowisko in ustawienia.STANOWISKA_BEZ_STOLU:
        return False
    if stanowisko not in jednostki:
        jednostki[stanowisko] = ustawienia.jednostka(stanowisko)
    status = STATION_PENDING_STATUS[stanowisko]
    if wiersz.product_id is not None:
        # Kafel-pozycja: leży, dopóki pozycja czeka na tym stanowisku.
        if jednostki[stanowisko] != 'pozycja':
            return False
        pozycja = pozycje.get(wiersz.product_id)
        return pozycja is not None and pozycja.current_status == status
    # Kafel-zamówienie: zamówienie ma tu pozycję i jest kompletne. Kafle wysłane przez biuro i startowe biuro
    # kładzie świadomie także dla niekompletnych (spec 5.7, 5.8) — leżą, dopóki jest tu choć jedna pozycja.
    if jednostki[stanowisko] != 'zamowienie':
        return False
    if not any(p.current_status == status for p in order.products):
        return False
    if wiersz.zrodlo in (stale.ZRODLO_BIURO, stale.ZRODLO_START):
        return True
    return kompletne_na(order, stanowisko)


def zdejmij_nieaktualne(order, *, teraz=None, zamkniecie_odlozen=False, worker_id=None, device_id=None):
    """
    Uzgadnia wiersze stołu zamówienia z bieżącymi statusami jego pozycji — jedna reguła dla wszystkich pisarzy,
    którzy zabierają pozycję ze stanowiska (ZAKOŃCZ, hurt, doróbka, zmiany z Base., cron): kafel `p:` zostaje
    tylko, gdy pozycja czeka na swoim stanowisku; kafel `o:` — gdy zamówienie ma tam pozycję i jest kompletne
    (spec 5.6 p. 2; kafle `biuro` i `start` także niekompletne). Zwraca kody stanowisk, z których coś zdjęła
    (do sygnałów).

    WARUNEK WSTĘPNY: wołający trzyma X na zamówieniu i jego pozycjach, a `order.products` to bieżący skład
    zamówienia (`blokady_zamowien.zablokuj_pozycje`) z naniesionymi już zmianami statusów.

    Najpierw flush: UPDATE-y pozycji wołającego idą do bazy przed blokadą wierszy stołu (kolejność z docstringu
    modułu). Wiersze stołu czytamy odczytem BIEŻĄCYM po `order_id` — zwykły odczyt nie widziałby kafla, który
    dopełnianie wstawiło po migawce żądania, i zostawiłby na stole kafel pozycji, która już poszła dalej.
    `zamkniecie_odlozen=True` (tylko ZAKOŃCZ) loguje `odlozenie_zamkniete` dla zdejmowanych kafli odłożonych;
    zdjęcie odłożonego kafla przez hurt, Base., doróbkę i cron nie loguje — odłożenie znika razem z kaflem (5.3).
    """
    db.session.flush()
    wiersze = (StationDesk.query.filter(StationDesk.order_id == order.id).order_by(StationDesk.id)
               .with_for_update().populate_existing().all())
    if not wiersze:
        return set()
    teraz = teraz or get_local_now()
    pozycje = {p.id: p for p in order.products}
    jednostki, zdjete = {}, set()
    for wiersz in wiersze:
        if _aktualny(wiersz, order, pozycje, jednostki):
            continue
        _usun_wiersz(wiersz, teraz, zamkniecie_odlozen, worker_id, device_id)
        zdjete.add(wiersz.station_code)
    return zdjete


# ── bramka ZAKOŃCZ (spec 5.5) ───────────────────────────────────────────────────────────────────────────────

def bramka_zakoncz(item, station_code, device, *, do_zapisu=False):
    """
    W trybie `stol` ZAKOŃCZ i licznik sztuk przyjmujemy tylko dla pozycji czekającej na tym stanowisku (inaczej
    `BladStolu('pozycja_poza_stanowiskiem', …, 409)`, K3-poprawka-2) i tylko dla kafla leżącego na stole albo
    odłożonego (inaczej `BladStolu('nie_na_stole', …, 409)`). Przepuszcza: stanowisko bez stołu (Lakiernia — zawsze,
    niezależnie od ustawień), tryb `stary`, starą appkę (`stara_appka`) oraz — na stanowisku zamówieniowym — pozycję
    zamówienia NIEKOMPLETNEGO (spec 5.6 p. 2: sekcja „Niekompletne” nie ma wiersza stołu, a formatować to, co
    przyszło, wolno; przepuszczamy każde niekompletne, nie tylko pokazane, bo policzenie ich kolejności wymagałoby
    czytania innych zamówień w transakcji trzymającej X).

    Status sprawdzamy PRZED wierszem stołu: kafel-zamówienie leży na stole także wtedy, gdy część pozycji jest już
    spakowana albo czeka gdzie indziej, a `complete_task` statusu nie sprawdza — ZAKOŃCZ takiej pozycji przestawiłby
    ją o stanowisko dalej (pozycję ze Sklejania przez ZAKOŃCZ Formatowania prosto na Krawędzie). Na stanowisku
    pozycyjnym pozycja spoza statusu i tak nie ma kafla — dostaje kod konkretny zamiast `nie_na_stole`, a appka
    porzuca wpis kolejki bez dodatkowych zapytań. Status czytamy z `item`: w ZAKOŃCZ to pozycja z blokady zamówienia
    (odczyt bieżący), w liczniku — zwykły odczyt, jak dotąd.

    `do_zapisu=True` (ZAKOŃCZ, pod blokadą X zamówienia): własny wiersz stołu odczytem bieżącym. `do_zapisu=False`
    (licznik sztuk — pisarz pozycji BEZ blokady zamówienia): zwykły odczyt; do odmowy wystarcza, a blokada wiersza
    stołu przed UPDATE pozycji odwróciłaby kolejność wobec ZAKOŃCZ (stół → pozycja kontra pozycja → stół).
    """
    if station_code in ustawienia.STANOWISKA_BEZ_STOLU:
        return
    if ustawienia.tryb(station_code) != 'stol':
        return
    if stara_appka(device):
        return
    if item.current_status != STATION_PENDING_STATUS[station_code]:
        raise BladStolu('pozycja_poza_stanowiskiem', u'Pozycja {} nie czeka na {}.'.format(
            item.short_product_id or u'#%d' % item.id,
            _NAZWA_MIEJSCOWNIK.get(station_code, station_label(station_code))), 409)
    jednostka = ustawienia.jednostka(station_code)
    zapytanie = StationDesk.query.filter(StationDesk.station_code == station_code,
                                         StationDesk.unit_key == klucz_kafla(item, station_code, jednostka))
    if do_zapisu:
        zapytanie = zapytanie.with_for_update().populate_existing()
    if zapytanie.first() is not None:
        return
    if jednostka == 'zamowienie' and item.order is not None and not kompletne_na(item.order, station_code):
        return
    raise BladStolu('nie_na_stole', u'Zamówienie {} nie leży na stole {}.'.format(
        _numer(item.order), _NAZWA_DOPELNIACZ.get(station_code, station_label(station_code))), 409)


# ══ Pisarze stołu: blokada stanowiska i odczyt kandydatów ═══════════════════════════════════════════════════
#
# KOLEJNOŚĆ BLOKAD DOPEŁNIANIA (spec 5.2, 9.4) — to samo dla „Wyślij”, „Zdejmij” i startu stołów:
#
#   COMMIT                                             # router: koniec migawki żądania
#   SELECT prod_config WHERE config_key = 'priorytety_blokada_<S>' FOR UPDATE       # jeden pisarz stołu na stanowisko
#   SELECT DISTINCT order_id FROM prod_products WHERE current_status = <status S>   # zwykły odczyt → migawka POD blokadą
#   SELECT prod_orders   WHERE id IN (…) ORDER BY id                FOR SHARE       # bieżące gwiazdki, ranga, sposób dostawy
#   SELECT prod_products WHERE order_id IN (…) ORDER BY order_id, id FOR SHARE      # bieżące statusy, skład zamówień
#   SELECT prod_station_desk WHERE station_code = <S>                               # ZWYKŁY odczyt — bez blokad wierszy stołu
#   INSERT prod_station_desk …                                     # FK → S na zamówieniu i pozycji (już trzymane)
#   COMMIT                                             # router; potem sygnał station:<S>
#
# Dlaczego osobne żądanie, a nie transakcja ZAKOŃCZ: ZAKOŃCZ trzyma X na zamówieniu A, a dopełnienie czyta pozycje
# innych zamówień; drugi tablet w ZAKOŃCZ zamówienia B trzymałby X na B i chciał czytać A — cykl (MySQL 1213).
# Dlaczego zamówienia → pozycje, a nie pozycje po statusie: wszyscy pisarze zamówienia biorą zamówienie przed
# pozycjami, więc dopełnianie czekające na S zamówienia A nie trzyma jeszcze żadnej jego pozycji, a pisarz nie
# czeka na nic, co dopełnianie trzyma (stół czyta ono bez blokad). Skan pozycji po indeksie statusu z FOR SHARE
# zakładałby do tego blokady luk na tym indeksie, w które UPDATE statusu z cudzego ZAKOŃCZ wstawia nowy wpis.
# Pozycja, która weszła w status S między migawką a blokadą zamówień, czeka do następnego dopełnienia (sygnał z
# ZAKOŃCZ i tak je wywoła). Rzadkie zakleszczenie z pisarzem spoza zasady „zamówienie najpierw” — jedno ponowienie
# w routerze.

Dopelnienie = namedtuple('Dopelnienie', 'pobrane kolejka_dalej niekompletne')
# Zamówienie niekompletne na stanowisku zamówieniowym: `brakuje` = [(pozycja, kod stanowiska, na którym czeka)].
Niekompletne = namedtuple('Niekompletne', 'order na_stanowisku pozycji brakuje')
# Stan stołu do odpowiedzi API (zwykłe odczyty): wiersze w kolejności `kafle`, kolejka i sekcja „Niekompletne”.
StanStolu = namedtuple('StanStolu', 'jednostka miejsca limit_odlozen wiersze kolejka_dalej niekompletne')
_Kandydaci = namedtuple('_Kandydaci', 'wiersze dorobki kolejka niekompletne zamowienia pozycje')

# Kolumny czytane odczytem bieżącym (zamówienie niesie etykietę kuriera, pozycja rysunki SVG — nie wczytujemy ich).
_KOLUMNY_ZAMOWIENIA = (
    ProductionOrder.id, ProductionOrder.internal_order_number, ProductionOrder.priority_stars,
    ProductionOrder.priority_rank, ProductionOrder.priority_rung, ProductionOrder.override_delivery_method,
)
_KOLUMNY_POZYCJI = widok._KOLUMNY_POZYCJI + (
    ProductionProduct.quantity, ProductionProduct.quantity_done_cutting, ProductionProduct.quantity_done_assembly,
    ProductionProduct.quantity_done_gluing, ProductionProduct.quantity_done_formatting,
    ProductionProduct.quantity_done_edges, ProductionProduct.quantity_done_painting,
    ProductionProduct.quantity_done_packaging,
)

# Status pozycji → stanowisko, na którym czeka.
STANOWISKO_STATUSU = {status: kod for kod, status in STATION_PENDING_STATUS.items()}
_ostrzezono_o_blokadzie = set()


def _prefiks(jednostka):
    return (KAFEL_ZAMOWIENIE if jednostka == 'zamowienie' else KAFEL_POZYCJA) + ':'


def wymagaj_stolu(station_code):
    """Stanowisko musi mieć stół: nieznany kod → 400 `stanowisko_nieznane`, Lakiernia → 409 `stanowisko_bez_stolu`
    (spec 5.5: pracuje z listy, stół nie powstaje nigdy). Wołać przed blokadą i zapisem."""
    if station_code not in STATION_PENDING_STATUS:
        raise BladStolu('stanowisko_nieznane', u'Nie ma takiego stanowiska.', 400)
    if station_code in ustawienia.STANOWISKA_BEZ_STOLU:
        raise BladStolu('stanowisko_bez_stolu', u'{} pracuje z listy, bez stołu.'.format(
            ustawienia.STANOWISKA_BEZ_STOLU[station_code]), 409)


def zablokuj_stanowisko(station_code):
    """
    Blokada „jeden pisarz stołu na stanowisko”: wiersz `prod_config` `priorytety_blokada_<S>` FOR UPDATE. MUSI być
    pierwszym poleceniem nowej transakcji — wołający (router) commituje tuż przed, bez żadnego odczytu pomiędzy.

    Brak wiersza (zakłada go migracja K1): na MySQL dopisujemy go sami (`INSERT IGNORE` w tej transakcji i ponowny
    odczyt — wzór `routes.zablokuj_trasy`); inne bazy (SQLite testów) nie blokują, ostrzeżenie raz na proces.
    """
    klucz = ustawienia.klucz_blokady(station_code)
    zapytanie = ProductionConfig.query.filter_by(config_key=klucz).with_for_update()
    wiersz = zapytanie.first()
    if wiersz is None and db.engine.dialect.name == 'mysql':
        teraz = get_local_now()
        db.session.execute(
            insert(ProductionConfig.__table__).prefix_with('IGNORE', dialect='mysql')
            .values(config_key=klucz, config_value='', config_type='string', created_at=teraz, updated_at=teraz,
                    config_description=u'Priorytety: blokada pobierania na stół stanowiska ' + station_code))
        wiersz = zapytanie.populate_existing().first()
        logger.warning('Brak wiersza blokady stołu w prod_config — założony (INSERT IGNORE)', extra={'klucz': klucz})
    if wiersz is None and klucz not in _ostrzezono_o_blokadzie:
        _ostrzezono_o_blokadzie.add(klucz)
        logger.warning('Brak wiersza blokady stołu w prod_config — pobieranie na stół NIE jest serializowane '
                       '(zakłada go migracja)', extra={'klucz': klucz})
    return wiersz


def _odczyt_kandydatow(station_code, biezacy):
    """
    (zamówienia rosnąco po id, wszystkie ich pozycje po (order_id, id)) dla zamówień, które mają pozycję w statusie
    stanowiska. `biezacy=True` — odczyt bieżący współdzielony (FOR SHARE + `populate_existing`), tylko pod blokadą
    stanowiska; `False` — zwykłe odczyty (widok). Zamówienia i pozycje trzymają się nawzajem silnymi referencjami
    (`order.products`, `pozycja.order`), jak po `blokady_zamowien.zablokuj_pozycje`.
    """
    status = STATION_PENDING_STATUS[station_code]
    ids = sorted({wiersz[0] for wiersz in db.session.query(ProductionProduct.order_id)
                  .filter(ProductionProduct.current_status == status).distinct().all()})
    return _wczytaj_zamowienia(ids, biezacy)


def _wczytaj_zamowienia(ids, biezacy):
    """
    (zamówienia `ids` rosnąco po id, wszystkie ich pozycje po (order_id, id)). `biezacy=True` — odczyt bieżący
    współdzielony (FOR SHARE + `populate_existing`), zamówienia PRZED pozycjami — kolejność wszystkich pisarzy
    zamówienia. Zamówienia i pozycje trzymają się nawzajem silnymi referencjami.
    """
    if not ids:
        return [], []
    zapytanie_zamowien = (ProductionOrder.query.options(load_only(*_KOLUMNY_ZAMOWIENIA))
                          .filter(ProductionOrder.id.in_(ids)).order_by(ProductionOrder.id))
    if biezacy:
        zapytanie_zamowien = zapytanie_zamowien.with_for_update(read=True).populate_existing()
    zamowienia = zapytanie_zamowien.all()
    if not zamowienia:
        return [], []
    zapytanie_pozycji = (ProductionProduct.query.options(load_only(*_KOLUMNY_POZYCJI))
                         .filter(ProductionProduct.order_id.in_([z.id for z in zamowienia]))
                         .order_by(ProductionProduct.order_id, ProductionProduct.id))
    if biezacy:
        zapytanie_pozycji = zapytanie_pozycji.with_for_update(read=True).populate_existing()
    pozycje = zapytanie_pozycji.all()
    pozycje_zamowien = {}
    for pozycja in pozycje:
        pozycje_zamowien.setdefault(pozycja.order_id, []).append(pozycja)
    for zamowienie in zamowienia:
        set_committed_value(zamowienie, 'products', pozycje_zamowien.get(zamowienie.id, []))
        for pozycja in pozycje_zamowien.get(zamowienie.id, []):
            set_committed_value(pozycja, 'order', zamowienie)
    return zamowienia, pozycje


def odczyt_biezacy_kandydatow(station_code):
    """Zamówienia i pozycje kandydatów odczytem bieżącym (FOR SHARE), w kolejności kanonicznej: zamówienia rosnąco
    po id → pozycje. Wołać pod blokadą stanowiska (`zablokuj_stanowisko`)."""
    return _odczyt_kandydatow(station_code, biezacy=True)


def uporzadkuj(wiersze):
    """Kolejność kafli (spec 5.1): na stole doróbki, wysłane przez biuro, startowe, pobrane z kolejki — w grupie po
    czasie wejścia; potem odłożone, najdłużej leżące pierwsze."""
    miejsce = {zrodlo: i for i, zrodlo in enumerate(stale.KOLEJNOSC_ZRODEL_NA_STOLE)}
    na_stole = sorted((w for w in wiersze if w.postponed_at is None),
                      key=lambda w: (miejsce.get(w.zrodlo, len(miejsce)), w.pulled_at, w.id))
    odlozone = sorted((w for w in wiersze if w.postponed_at is not None), key=lambda w: (w.postponed_at, w.id))
    return na_stole + odlozone


def kafle(station_code, jednostka=None):
    """
    Wiersze stołu stanowiska w BIEŻĄCEJ jednostce: najpierw leżące na stole, potem odłożone — w jednej, ustalonej
    kolejności (`uporzadkuj`), tej samej dla odpowiedzi `desk`, `postpone` i panelu (dwa tablety stanowiska pokazują
    to samo, appka nie sortuje). ZAWSZE zwykły odczyt: wierszy stołu całego stanowiska nikt nie blokuje.
    """
    if jednostka is None:
        jednostka = ustawienia.jednostka(station_code)
    prefiks = _prefiks(jednostka)
    wiersze = StationDesk.query.filter(StationDesk.station_code == station_code).order_by(StationDesk.id).all()
    return uporzadkuj([w for w in wiersze if w.unit_key.startswith(prefiks)])


def _kandydaci(station_code, jednostka, zamowienia, pozycje):
    """
    Kandydaci stanowiska policzeni z wczytanych zamówień i pozycji (odczyt bieżący albo zwykły — decyduje wołający):
    zwykłe odczyty tras, wierszy stołu i konfiguracji, wejście przez `widok.wejscie_kandydatow` (jedno miejsce dla
    stołu i podglądu panelu), kolejność z `kolejka.kandydaci_stanowiska` — bez własnego sortowania.

    Zwraca wiersze stołu (bieżąca jednostka, kolejność `uporzadkuj`) oraz id kafli w kolejności algorytmu: doróbki
    (początek kolejki, wchodzą pierwsze w ramach K — spec 5.1; na stanowisku zamówieniowym to KOMPLETNE zamówienie
    z doróbką czekającą na tym stanowisku), kolejka (pozostali kandydaci) i niekompletne. Pakowanie: zamówienie bez
    sposobu dostawy jest zwykłym kandydatem (logistyka 4.6 — spakuje się z etykietą „NIE USTAWIONO”, spec 5.1).
    """
    ids = [zamowienie.id for zamowienie in zamowienia]
    trasa_zamowienia = {}
    if ids:
        trasa_zamowienia = dict(db.session.query(RouteStop.order_id, RouteStop.route_id)
                                .join(Route, Route.id == RouteStop.route_id)
                                .filter(RouteStop.order_id.in_(ids),
                                        Route.status.in_(stale.STATUSY_TRASY_NA_DRABINIE)).all())
    wiersze = kafle(station_code, jednostka)
    status = STATION_PENDING_STATUS[station_code]
    # Konfiguracje pozycji w statusie stanowiska jednym zapytaniem; lista trzyma je w sesji do końca funkcji, więc
    # `pozycja.configuration` w `wejscie_kandydatow` nie robi zapytań.
    id_konfiguracji = sorted({p.configuration_id for p in pozycje
                              if p.current_status == status and p.configuration_id is not None})
    konfiguracje = (ProductionConfiguration.query.filter(ProductionConfiguration.id.in_(id_konfiguracji)).all()
                    if id_konfiguracji else [])
    pozycje_stanowiska, statusy_zamowien = widok.wejscie_kandydatow(
        station_code, zamowienia, pozycje, trasa_zamowienia, {w.unit_key for w in wiersze})
    wynik = kolejka.kandydaci_stanowiska(
        station_code, pozycje_stanowiska, statusy_zamowien,
        szczebel_rozpoczete=drabina.pozycja_tagu(stale.TAG_ROZPOCZETE), jednostka=jednostka,
        omijajace=widok.omijajace_stanowisko(station_code, pozycje))
    del konfiguracje

    zamowienia_po_id = {zamowienie.id: zamowienie for zamowienie in zamowienia}
    pozycje_po_id = {pozycja.id: pozycja for pozycja in pozycje}

    if jednostka == 'zamowienie':
        z_dorobka = {p.order_id for p in pozycje_stanowiska if p.dorobka}
        dorobki = [order_id for order_id in wynik.kafle if order_id in z_dorobka]
        kolejka_stolu = [order_id for order_id in wynik.kafle if order_id not in z_dorobka]
        niekompletne = list(wynik.niekompletne)
    else:
        stanowiska_po_id = {p.id: p for p in pozycje_stanowiska}
        dorobki = [product_id for product_id in wynik.kafle if stanowiska_po_id[product_id].dorobka]
        kolejka_stolu = [product_id for product_id in wynik.kafle if not stanowiska_po_id[product_id].dorobka]
        niekompletne = []
    return _Kandydaci(wiersze=wiersze, dorobki=dorobki, kolejka=kolejka_stolu, niekompletne=niekompletne,
                      zamowienia=zamowienia_po_id, pozycje=pozycje_po_id)


def _lista_niekompletnych(kandydaci, ile):
    """Pierwsze `ile` zamówień niekompletnych (w kolejności rangi) z listą brakujących pozycji i stanowiskami,
    na których czekają."""
    return [Niekompletne(order=kandydaci.zamowienia[order_id], na_stanowisku=na_stanowisku, pozycji=pozycji,
                         brakuje=[(kandydaci.pozycje[product_id], STANOWISKO_STATUSU.get(status))
                                  for product_id, status in brakuje if product_id in kandydaci.pozycje])
            for order_id, na_stanowisku, pozycji, brakuje in kandydaci.niekompletne[:ile]]


def _nowy_wiersz(station_code, jednostka, kafel_id, kandydaci, zrodlo, teraz, user_id=None):
    """Wiersz stołu dla kafla `kafel_id` (id pozycji albo zamówienia, wg jednostki) — dodany do sesji."""
    if jednostka == 'zamowienie':
        wiersz = StationDesk(station_code=station_code, order_id=kafel_id, product_id=None,
                             unit_key=klucz_zamowienia(kafel_id))
    else:
        wiersz = StationDesk(station_code=station_code, order_id=kandydaci.pozycje[kafel_id].order_id,
                             product_id=kafel_id, unit_key=klucz_pozycji(kafel_id))
    wiersz.pulled_at = teraz
    wiersz.zrodlo = zrodlo
    wiersz.sent_by_user_id = user_id
    db.session.add(wiersz)
    return wiersz


# ══ Limit czekania na blokady w dopełnianiu ═════════════════════════════════════════════════════════════════
#
# `GET desk` wołają wszystkie tablety stanowiska — co 30 s przy pustym stole i po każdym sygnale — a dopełnienie
# czyta odczytem bieżącym zamówienia i pozycje WSZYSTKICH kandydatów. Jedna cudza blokada zamówienia trzymana długo
# (ręczna transakcja w kliencie bazy, zapis czekający na coś zewnętrznego) zatrzymałaby każde takie żądanie na
# limicie serwera (50 s; gunicorn ubija żądanie po 30 s), a kolejne ustawiałyby się na wierszu blokady stanowiska.
# Kilka wiszących `desk` zajmuje wszystkie workery i CRM staje dla wszystkich. Dlatego transakcja dopełnienia
# czeka na blokadę najwyżej `kolejka.LIMIT_CZEKANIA_NA_BLOKADE_S` (ten sam bezpiecznik co w `kolejka.utrwal`);
# po przekroczeniu (MySQL 1205) `desk` oddaje stół bez dopełnienia, a wolne miejsce zajmie następne wywołanie.
#
# Limit jest zmienną SESJI MySQL, czyli własnością połączenia z puli: wraca do wartości serwera PRZED commitem
# i rollbackiem (te oddają połączenie do puli). Krótki limit w puli trafiłby do ZAKOŃCZ albo hurtu innego żądania,
# które mają czekać tyle, co dotąd.

KOD_LIMIT_CZEKANIA = kolejka._KOD_LIMIT_CZEKANIA


def _uniewaznij_polaczenie(polaczenie):
    """Połączenie, któremu nie udało się przywrócić limitu czekania, nie może wrócić do puli. Niczego nie rzuca."""
    try:
        polaczenie.invalidate()
        return
    except Exception as e:
        # Połączenie jest już zamknięte, czyli oddane do puli razem z krótkim limitem (ktoś zakończył transakcję
        # w zasięgu limitu). Nie da się go wskazać — wymieniamy całą pulę: stare połączenia zostają zamknięte.
        logger.error('Stół: połączenie z krótkim limitem czekania wróciło do puli — wymieniam pulę połączeń',
                     extra={'error': str(e)})
    try:
        db.engine.dispose()
    except Exception as e:
        logger.error('Stół: nieudana wymiana puli połączeń', extra={'error': str(e)})


def _przywroc_limit_czekania(polaczenie):
    try:
        kolejka._wyslij_ustawienie(polaczenie, kolejka._SQL_PRZYWROC_LIMIT)
    except Exception as e:
        logger.warning('Stół: nie udało się przywrócić limitu czekania na blokadę — unieważniam połączenie',
                       extra={'error': str(e)})
        _uniewaznij_polaczenie(polaczenie)


@contextmanager
def krotkie_czekanie_na_blokady():
    """
    Zasięg, w którym bieżąca transakcja `db.session` czeka na cudzą blokadę wiersza najwyżej
    `kolejka.LIMIT_CZEKANIA_NA_BLOKADE_S` sekund (MySQL; inne bazy — bez zmian). Wołać TUŻ PO commicie, jako
    pierwszą rzecz nowej transakcji: `SET SESSION` niczego nie czyta, więc blokada stanowiska dalej jest pierwszym
    odczytem. Wyjście z zasięgu — także wyjątkiem — przywraca limit na TYM SAMYM połączeniu; wołający commituje
    albo cofa dopiero potem.

    W zasięgu nie ma autoflusha: nieudany flush cofa transakcję sesji i oddaje jej połączenie do puli, zanim limit
    zostałby przywrócony. Oczekujące INSERT-y idą przy commicie wołającego, już z limitem serwera.
    """
    polaczenie = db.session.connection()
    z_limitem = kolejka._ma_limit_czekania(polaczenie)
    if z_limitem:
        kolejka._wyslij_ustawienie(polaczenie, kolejka._SQL_USTAW_LIMIT)
    try:
        with db.session.no_autoflush:       # także poza MySQL: testy na SQLite mają ten sam porządek zapisów
            yield
    finally:
        if z_limitem:
            _przywroc_limit_czekania(polaczenie)


def dopelnij(station_code, *, teraz=None):
    """
    Dopełnia stół stanowiska z kolejki (spec 5.1–5.2): blokada stanowiska → ustawienia → kandydaci odczytem bieżącym
    → INSERT wierszy. Bez commita: commituje router (`GET desk`), który commituje też TUŻ PRZED wywołaniem.

    - do K liczą się WSZYSTKIE kafle leżące na stole w bieżącej jednostce (bez odłożonych), niezależnie od źródła —
      także doróbki, wysłane przez biuro i startowe; dobieramy dopiero, gdy jest ich mniej niż K;
    - doróbki czekające na stanowisku stoją na początku kolejki i wchodzą pierwsze, W RAMACH K
      (`zrodlo='dorobka'`), potem reszta kolejki (`zrodlo='kolejka'`);
    - stanowisko zamówieniowe bierze tylko zamówienia kompletne; niekompletne wracają osobno (do K sztuk);
    - kafle odłożone i leżące na stole nie są pobierane ponownie.

    Zwraca `Dopelnienie(pobrane, kolejka_dalej, niekompletne)`: nowe wiersze, liczbę kandydatów, którzy zostali
    w kolejce, i sekcję „Niekompletne”.
    """
    wymagaj_stolu(station_code)
    zablokuj_stanowisko(station_code)
    # Ustawienia PO blokadzie: to zwykłe odczyty `prod_config`, a między commitem a blokadą nie wolno nic czytać.
    miejsca = ustawienia.miejsca(station_code)
    jednostka = ustawienia.jednostka(station_code)
    zamowienia, pozycje = odczyt_biezacy_kandydatow(station_code)
    kandydaci = _kandydaci(station_code, jednostka, zamowienia, pozycje)
    teraz = teraz or get_local_now()

    # Doróbki stoją na początku kolejki i wchodzą w ramach K (decyzja Konrada 5.10 — wersja „ponad K” kładła
    # pierwszego dnia wszystkie zaległe doróbki naraz); różni je tylko źródło wiersza.
    na_stole = sum(1 for wiersz in kandydaci.wiersze if wiersz.postponed_at is None)
    w_kolejce = ([(kafel_id, stale.ZRODLO_DOROBKA) for kafel_id in kandydaci.dorobki]
                 + [(kafel_id, stale.ZRODLO_KOLEJKA) for kafel_id in kandydaci.kolejka])
    wchodza = w_kolejce[:max(0, miejsca - na_stole)]
    pobrane = [_nowy_wiersz(station_code, jednostka, kafel_id, kandydaci, zrodlo, teraz)
               for kafel_id, zrodlo in wchodza]
    return Dopelnienie(pobrane=pobrane, kolejka_dalej=len(w_kolejce) - len(wchodza),
                       niekompletne=_lista_niekompletnych(kandydaci, miejsca))


def stan(station_code):
    """
    Stan stołu do odpowiedzi API (`desk`, `postpone`) — same ZWYKŁE odczyty, bez blokad i zapisów: wiersze stołu
    w kolejności `kafle`, liczba kafli czekających w kolejce (razem z doróbkami jeszcze nie pobranymi) i sekcja
    „Niekompletne” (do K sztuk). Liczy tą samą drogą co `dopelnij`.
    """
    jednostka = ustawienia.jednostka(station_code)
    miejsca = ustawienia.miejsca(station_code)
    zamowienia, pozycje = _odczyt_kandydatow(station_code, biezacy=False)
    kandydaci = _kandydaci(station_code, jednostka, zamowienia, pozycje)
    return StanStolu(jednostka=jednostka, miejsca=miejsca, limit_odlozen=ustawienia.limit(station_code),
                     wiersze=kandydaci.wiersze, kolejka_dalej=len(kandydaci.dorobki) + len(kandydaci.kolejka),
                     niekompletne=_lista_niekompletnych(kandydaci, miejsca))


# ══ Odłóż (spec 5.3) ════════════════════════════════════════════════════════════════════════════════════════
#
# KOLEJNOŚĆ BLOKAD (spec 9.4 „ZAKOŃCZ/Odłóż: kolejność dzisiejsza”): [pracownicy] → X zamówienie → X pozycje
# (handler: `zablokuj_zamowienie_pozycji`) → SELECT prod_station_desk WHERE station_code = ? AND unit_key = ? FOR
# UPDATE (własny wiersz) → zwykły SELECT COUNT(*) odłożonych stanowiska → UPDATE wiersza → INSERT prod_priority_log
# (FK zamówienia już X) → commit (dekorator) → sygnał. Odłóż nie bierze blokady stanowiska i blokuje wyłącznie
# wiersz własnego kafla, więc nie czeka na ZAKOŃCZ, hurt ani Odłóż innego zamówienia.
#
# LIMIT JEST MIĘKKI: liczbę otwartych odłożeń stanowiska czytamy zwykłym odczytem (migawka żądania). Odczyt bieżący
# wierszy całego stanowiska dawałby cykl blokad z ZAKOŃCZ innych zamówień (docstring modułu), a handler pod
# `with_idempotency` nie może zacząć nowej transakcji. Koszt: dwa Odłóż na jednym stanowisku w tej samej chwili mogą
# przekroczyć limit o 1 — limit to bariera dyscypliny, nie niezmiennik danych.

_NAZWY_KAFLI = {
    # jednostka → (1, 2–4, 5+) z przymiotnikiem i zaimkami do zdania o limicie
    'pozycja': ((u'odłożona pozycja', u'odłożone pozycje', u'odłożonych pozycji'), u'którąś', u'kolejną'),
    'zamowienie': ((u'odłożone zamówienie', u'odłożone zamówienia', u'odłożonych zamówień'), u'któreś', u'kolejne'),
}


def komunikat_limitu(station_code, liczba, jednostka):
    """„Na Sklejaniu leży 10 odłożonych pozycji. Zamknij którąś, zanim odłożysz kolejną.” — z polską odmianą."""
    formy, ktoras, kolejna = _NAZWY_KAFLI['zamowienie' if jednostka == 'zamowienie' else 'pozycja']
    if liczba == 1:
        czasownik, nazwa = u'leży', formy[0]
    elif liczba % 10 in (2, 3, 4) and liczba % 100 not in (12, 13, 14):
        czasownik, nazwa = u'leżą', formy[1]
    else:
        czasownik, nazwa = u'leży', formy[2]
    return u'Na {} {} {} {}. Zamknij {}, zanim odłożysz {}.'.format(
        _NAZWA_MIEJSCOWNIK.get(station_code, station_label(station_code)), czasownik, liczba, nazwa, ktoras, kolejna)


def odloz(order_id, product_id, station_code, powod, notatka, worker_id, device_id, *, teraz=None):
    """
    Odkłada kafel leżący na stole: pozycję (`product_id`) albo całe zamówienie (`product_id=None`). Kafel zostaje
    wierszem stołu (sekcja „Odłożone” na tablecie), nie wraca do kolejki i nie jest pobierany ponownie; da się go
    zakończyć w każdej chwili. Zwraca wiersz stołu. Bez commita.

    WARUNEK WSTĘPNY: wołający trzyma X na zamówieniu i jego pozycjach (`blokady_zamowien.zablokuj_zamowienie_pozycji`).

    Odmowy (`BladStolu`): 400 `powod_niepoprawny` (powód spoza listy, `inne` bez notatki), 409 `nie_na_stole` (kafla
    nie ma na stole albo jest już odłożony — np. drugi tablet właśnie go zakończył), 409 `limit_odlozen`.
    """
    wymagaj_stolu(station_code)
    notatka = (notatka or u'').strip() or None
    if powod not in stale.POWODY_ODLOZENIA:
        raise BladStolu('powod_niepoprawny', u'Wybierz powód odłożenia z listy.', 400)
    if powod == 'inne' and notatka is None:
        raise BladStolu('powod_niepoprawny', u'Przy powodzie „inne” wpisz, dlaczego odkładasz.', 400)

    klucz = klucz_pozycji(product_id) if product_id is not None else klucz_zamowienia(order_id)
    wiersz = (StationDesk.query
              .filter(StationDesk.station_code == station_code, StationDesk.unit_key == klucz)
              .with_for_update().populate_existing().first())
    if wiersz is None or wiersz.postponed_at is not None:
        raise BladStolu('nie_na_stole', u'Zamówienie {} nie leży na stole {}.'.format(
            _numer(db.session.get(ProductionOrder, order_id)),
            _NAZWA_DOPELNIACZ.get(station_code, station_label(station_code))), 409)

    odlozonych = (db.session.query(func.count(StationDesk.id))
                  .filter(StationDesk.station_code == station_code, StationDesk.postponed_at.isnot(None)).scalar())
    if odlozonych >= ustawienia.limit(station_code):
        raise BladStolu('limit_odlozen', komunikat_limitu(
            station_code, odlozonych, 'pozycja' if product_id is not None else 'zamowienie'), 409)

    teraz = teraz or get_local_now()
    wiersz.postponed_at = teraz
    wiersz.postpone_reason = powod
    wiersz.postpone_note = notatka
    wiersz.postponed_by_worker_id = worker_id
    wiersz.postponed_device_id = device_id
    db.session.add(PriorityLog(action='odlozenie', order_id=order_id, product_id=product_id,
                               station_code=station_code, reason=powod, note=notatka, worker_id=worker_id,
                               device_id=device_id, created_at=teraz))
    return wiersz


# ══ Pole `priorytet` pozycji dla tabletu (spec 6.1) ═════════════════════════════════════════════════════════

def _miejsca_w_zamowieniach(wiersze):
    """
    {product_id: "i/n"} — miejsce pozycji w zamówieniu. `n` = liczba niezanulowanych pozycji zamówienia, `i` =
    miejsce po (`product_sequence_in_order`, id). Doróbka nie jest osobną pozycją: stoi w miejscu oryginału (także
    gdy oryginał został odrzucony w całości i jest anulowany). Pozycja anulowana bez żywej doróbki → None.
    `wiersze` — (id, order_id, product_sequence_in_order, original_product_id, current_status) WSZYSTKICH pozycji
    zamówień.
    """
    zamowienia = {}
    for wiersz in wiersze:
        zamowienia.setdefault(wiersz.order_id, []).append(wiersz)
    wynik = {}
    for lista in zamowienia.values():
        oryginal = {w.id: w.original_product_id for w in lista}

        def korzen(product_id):
            # Doróbka doróbki wskazuje na doróbkę — idziemy do pierwszego oryginału (z bezpiecznikiem na cykl).
            for _ in range(len(oryginal) + 1):
                rodzic = oryginal.get(product_id)
                if rodzic is None or rodzic not in oryginal:
                    return product_id
                product_id = rodzic
            return product_id

        miejsca = {}                    # korzeń → [najmniejsza kolejność, czy żyje, id członków]
        for w in lista:
            miejsce = miejsca.setdefault(korzen(w.id), [w.product_sequence_in_order or 0, False, []])
            miejsce[0] = min(miejsce[0], w.product_sequence_in_order or 0)
            miejsce[1] = miejsce[1] or w.current_status != 'anulowane'
            miejsce[2].append(w.id)
        zywe = sorted((dane[0], klucz) for klucz, dane in miejsca.items() if dane[1])
        numer = {klucz: i for i, (_kolejnosc, klucz) in enumerate(zywe, start=1)}
        for klucz, (_kolejnosc, zyje, czlonkowie) in miejsca.items():
            for product_id in czlonkowie:
                wynik[product_id] = '%d/%d' % (numer[klucz], len(zywe)) if zyje else None
    return wynik


def kontekst_priorytetu(items, komplet=False):
    """
    {id pozycji: priorytet} dla serializera API mobilnego (spec 6.1):
    `{'gwiazdki', 'szczebel', 'trasa', 'pozycja_w_zamowieniu'}`. Listy liczą to RAZ na żądanie i podają
    `serialize_order(..., priorytety=)`; dwa zwykłe zapytania na całą listę (drabina, pozycje zamówień).

    - `gwiazdki` — `prod_orders.priority_stars`;
    - `szczebel` — `'dorobka'` dla doróbki, inaczej rodzaj szczebla zamówienia: `'trasa'`, `'gwiazdki'` albo kod tagu
      (`po_terminie`, `blisko_terminu`, `rozpoczete`). Rodzaj wynika z `prod_orders.priority_rung`, czyli indeksu
      wśród szczebli WIDOCZNYCH (`drabina.szczeble()`), nie z kolumny `position` — ta numeruje też ukryte szczeble
      tras załadowanych. Brak rangi (zamówienie jeszcze nieprzeliczone) albo indeks spoza drabiny → None;
    - `trasa` — `{'id', 'nazwa', 'data'}` tylko gdy szczebel to trasa (robocza albo zatwierdzona);
    - `pozycja_w_zamowieniu` — `"2/5"` (`_miejsca_w_zamowieniach`).

    `komplet=True` — wołający podaje WSZYSTKIE pozycje każdego zamówienia z listy (lista stanowiska, stół), więc
    miejsca liczymy z samych `items`, bez zapytania o pozycje zamówień.

    Kolumny rangi są pamięcią podręczną z ostatniego `kolejka.utrwal()`, więc plakietka tagu może być chwilę
    nieaktualna — jak ranga na liście.
    """
    items = [item for item in items if item is not None]
    if not items:
        return {}
    # Drabinę czytamy tylko, gdy któreś zamówienie ma zapisany szczebel (przed pierwszym przeliczeniem nie ma go nikt).
    widoczne = []
    if any(item.order is not None and item.order.priority_rung is not None for item in items):
        widoczne = drabina.szczeble()
    id_zamowien = sorted({item.order_id for item in items if item.order_id is not None})
    miejsca = {}
    if komplet:
        miejsca = _miejsca_w_zamowieniach(items)
    elif id_zamowien:
        miejsca = _miejsca_w_zamowieniach(
            db.session.query(ProductionProduct.id, ProductionProduct.order_id,
                             ProductionProduct.product_sequence_in_order, ProductionProduct.original_product_id,
                             ProductionProduct.current_status)
            .filter(ProductionProduct.order_id.in_(id_zamowien)).all())

    zamowien = {}                       # order_id → (gwiazdki, szczebel, trasa) — to samo dla każdej pozycji

    def z_zamowienia(order):
        if order.id not in zamowien:
            szczebel, trasa = None, None
            indeks = order.priority_rung
            if indeks is not None and 1 <= indeks <= len(widoczne):
                wiersz = widoczne[indeks - 1]
                if wiersz.kind == 'stars':
                    szczebel = 'gwiazdki'
                elif wiersz.kind == 'tag':
                    szczebel = wiersz.tag
                else:
                    szczebel = 'trasa'
                    if wiersz.route is not None:
                        trasa = {'id': wiersz.route.id, 'nazwa': wiersz.route.name,
                                 'data': wiersz.route.date_from.isoformat() if wiersz.route.date_from else None}
            zamowien[order.id] = (int(order.priority_stars or 0), szczebel, trasa)
        return zamowien[order.id]

    wynik = {}
    for item in items:
        gwiazdki, szczebel, trasa = z_zamowienia(item.order) if item.order is not None else (0, None, None)
        if item.original_product_id is not None:
            szczebel, trasa = 'dorobka', None
        wynik[item.id] = {'gwiazdki': gwiazdki, 'szczebel': szczebel, 'trasa': trasa,
                          'pozycja_w_zamowieniu': miejsca.get(item.id)}
    return wynik


def priorytet_zamowienia(pozycje, priorytety):
    """Priorytet na poziomie kafla-zamówienia: gwiazdki, szczebel i trasa zamówienia — bez miejsca pozycji i bez
    plakietki doróbki (te są na pozycjach). `pozycje` — pozycje jednego zamówienia, `priorytety` — mapa
    z `kontekst_priorytetu`."""
    wpisy = [priorytety[p.id] for p in pozycje if p.id in priorytety]
    if not wpisy:
        return None
    # Pozycja niebędąca doróbką niesie szczebel zamówienia; gdy są same doróbki — nie wiemy, zostaje `dorobka`.
    wzor = next((w for w in wpisy if w['szczebel'] != 'dorobka'), wpisy[0])
    return {'gwiazdki': wzor['gwiazdki'], 'szczebel': wzor['szczebel'], 'trasa': wzor['trasa']}


# ══ „Wyślij na stanowisko” i „Zdejmij ze stołu” — biuro (spec 5.7) ══════════════════════════════════════════
#
# KOLEJNOŚĆ BLOKAD (spec 9.4, jak dopełnianie): [commit routera] → `priorytety_blokada_<S>` FOR UPDATE → zamówienie
# FOR SHARE → jego pozycje FOR SHARE → wiersze stołu WŁASNEGO zamówienia odczytem bieżącym po (station_code,
# unit_key) → INSERT / UPDATE / DELETE → [commit routera] → sygnał `station:<S>`. Bez blokad X zamówień i bez
# blokady tras.
#
# Blokada S na zamówieniu i pozycjach wyklucza się z każdym pisarzem TEGO zamówienia (ZAKOŃCZ, Odłóż, hurt — biorą
# X na zamówieniu, zanim dotkną jego wierszy stołu), a blokada stanowiska — z dopełnianiem i innymi pisarzami stołu.
# Wiersz stołu czytamy tu odczytem bieżącym, nie zwykłym: „Zdejmij” zna tylko klucz kafla, więc zamówienie kafla
# ustala zwykłym odczytem (migawka powstaje PRZED blokadą zamówienia), a ZAKOŃCZ mógł zdjąć kafel w tym oknie —
# zwykły odczyt pokazałby wiersz, którego już nie ma. Blokujemy wyłącznie wiersze własnego zamówienia (rekordy po
# kluczu unikalnym), nigdy wierszy całego stanowiska.
#
# Co zostaje: klucz, którego na stole jeszcze nie ma, daje przy odczycie bieżącym blokadę LUKI na indeksie
# unikalnym. Luki nie kolidują ze sobą ani z DELETE cudzego ZAKOŃCZ, kolidują tylko ze wstawieniem w tę samą lukę.
# Dwa „Wyślij” naraz na RÓŻNYCH stanowiskach (różne blokady stanowiska), których nowe klucze wpadają w tę samą lukę
# (koniec zakresu jednego stanowiska i początek następnego), zablokują więc sobie nawzajem INSERT — MySQL 1213,
# jedno ponowienie w routerze panelu (`_zapis_z_ponowieniem`). Dopełnianie i start stołów nie czytają stołu
# odczytem bieżącym, więc w tym cyklu nie uczestniczą.

_KLUCZ_KAFLA = re.compile(r'^([po]):([1-9][0-9]{0,17})$')


def _wiersze_do_zapisu(station_code, klucze):
    """
    {unit_key: wiersz} — wiersze stołu o podanych kluczach, odczytem BIEŻĄCYM (FOR UPDATE). Wołać pod blokadą
    stanowiska i blokadą S zamówienia, do którego te kafle należą.

    KAŻDY KLUCZ OSOBNYM ZAPYTANIEM, równością po obu kolumnach klucza unikalnego, w ustalonej kolejności kluczy —
    na MySQL dostęp `const`: blokada jednego rekordu (albo samej luki, gdy kafla nie ma). Jedno zapytanie
    `unit_key IN (…) ORDER BY id` optymalizator wykonuje od trzech kluczy skanem `ix_prod_station_desk_station_code`,
    a w małej tabeli skanem klucza głównego (EXPLAIN na MySQL 8.4, raport kroku K3) — i blokuje wtedy wiersze
    CAŁEGO stanowiska albo całej tabeli, czyli cudze kafle: cykl z ZAKOŃCZ innego zamówienia (docstring modułu).
    """
    wiersze = {}
    for klucz in sorted(set(klucze)):
        wiersz = (StationDesk.query
                  .filter(StationDesk.station_code == station_code, StationDesk.unit_key == klucz)
                  .with_for_update().populate_existing().first())
        if wiersz is not None:
            wiersze[klucz] = wiersz
    return wiersze


def wyslij(station_code, order_id, user_id, *, teraz=None):
    """
    „Wyślij na stanowisko” (spec 5.7, ustalenie 18): biuro kładzie na stół stanowiska kafle zamówienia, które są
    TERAZ w statusie tego stanowiska — bez przeskakiwania procesu. Jednostka `pozycja`: każda taka pozycja jako
    osobny kafel; `zamowienie`: kafel zamówienia, także niekompletnego (biuro wypycha je świadomie; ZAKOŃCZ pozycji
    działa jak w „Niekompletnych”). Ponad K, `zrodlo='biuro'` — na stole zaraz po doróbkach.

    Kafel już leżący na stole zostaje bez zmian; kafel ODŁOŻONY wraca na stół (jedyne „przywróć” odłożenia — robi je
    biuro, nie tablet). Działa w trybie `stary` i `stol`. Zwraca `{'wyslane': [...], 'przywrocone': [...],
    'juz_na_stole': [...]}` (klucze kafli). Bez commita; wołający commituje TUŻ PRZED wywołaniem i po nim.

    Odmowy (`BladStolu`): 409 `stanowisko_bez_stolu` (Lakiernia), 404 `zamowienie_nieznane`, 409
    `brak_na_stanowisku`. Sposobu dostawy nie sprawdzamy: od logistyki 4.6 Pakowanie go nie wymaga (spec 5.1).
    """
    wymagaj_stolu(station_code)
    zablokuj_stanowisko(station_code)
    zamowienia, _pozycje = _wczytaj_zamowienia([order_id], biezacy=True)
    if not zamowienia:
        raise BladStolu('zamowienie_nieznane', u'Nie ma takiego zamówienia.', 404)
    zamowienie = zamowienia[0]
    status = STATION_PENDING_STATUS[station_code]
    na_stanowisku = [pozycja for pozycja in zamowienie.products if pozycja.current_status == status]
    if not na_stanowisku:
        raise BladStolu('brak_na_stanowisku', u'Zamówienie {} nie ma teraz żadnej pozycji na {}.'.format(
            _numer(zamowienie), _NAZWA_MIEJSCOWNIK.get(station_code, station_label(station_code))), 409)

    # Ustawienia po blokadach: to zwykłe odczyty, a pierwszy z nich zakłada migawkę transakcji.
    if ustawienia.jednostka(station_code) == 'zamowienie':
        cele = [(klucz_zamowienia(zamowienie.id), None)]
    else:
        cele = [(klucz_pozycji(pozycja.id), pozycja.id) for pozycja in na_stanowisku]
    istniejace = _wiersze_do_zapisu(station_code, [klucz for klucz, _product_id in cele])
    teraz = teraz or get_local_now()
    wynik = {'wyslane': [], 'przywrocone': [], 'juz_na_stole': []}
    for klucz, product_id in cele:
        wiersz = istniejace.get(klucz)
        if wiersz is not None and wiersz.postponed_at is None:
            wynik['juz_na_stole'].append(klucz)
            continue
        log = PriorityLog(action='wyslanie', order_id=zamowienie.id, product_id=product_id,
                          station_code=station_code, new_value=klucz, user_id=user_id, created_at=teraz)
        if wiersz is None:
            wiersz = StationDesk(station_code=station_code, order_id=zamowienie.id, product_id=product_id,
                                 unit_key=klucz)
            db.session.add(wiersz)
            wynik['wyslane'].append(klucz)
        else:
            # Odłożony kafel wraca na stół; powód odłożenia zostaje w historii.
            log.old_value, log.reason, log.note = 'odlozone', wiersz.postpone_reason, wiersz.postpone_note
            wiersz.postponed_at = None
            wiersz.postpone_reason = None
            wiersz.postpone_note = None
            wiersz.postponed_by_worker_id = None
            wiersz.postponed_device_id = None
            wynik['przywrocone'].append(klucz)
        wiersz.pulled_at = teraz
        wiersz.zrodlo = stale.ZRODLO_BIURO
        wiersz.sent_by_user_id = user_id
        db.session.add(log)
    return wynik


def zdejmij_przez_biuro(station_code, unit_key_kafla, user_id, *, teraz=None):
    """
    „Zdejmij ze stołu” (spec 5.7): biuro usuwa wiersz stołu — kafel leżący na stole albo odłożony. Pozycja zostaje
    na stanowisku, więc kafel wraca do kolejki (dopełnianie może go wziąć znowu). Służy poprawkom podglądu startu
    i pomyłkom biura. Zwraca `{'unit_key', 'order_id', 'product_id', 'odlozony'}`. Bez commita.

    Odmowy (`BladStolu`): 400 `dane_niepoprawne` (zły klucz kafla), 409 `stanowisko_bez_stolu`, 404 `brak_kafla`.
    """
    wymagaj_stolu(station_code)
    if not isinstance(unit_key_kafla, str) or not _KLUCZ_KAFLA.match(unit_key_kafla):
        raise BladStolu('dane_niepoprawne', u'Podaj klucz kafla (unit_key) z listy stołów.', 400)
    zablokuj_stanowisko(station_code)
    # Zamówienie kafla — zwykłym odczytem wiersza stołu (pod blokadą stanowiska nikt nie wstawi tu nowego kafla).
    order_id = (db.session.query(StationDesk.order_id)
                .filter(StationDesk.station_code == station_code, StationDesk.unit_key == unit_key_kafla).scalar())
    if order_id is not None:
        _wczytaj_zamowienia([order_id], biezacy=True)
    wiersz = _wiersze_do_zapisu(station_code, [unit_key_kafla]).get(unit_key_kafla) if order_id is not None else None
    if wiersz is None:
        raise BladStolu('brak_kafla', u'Tego kafla nie ma już na stole.', 404)
    odlozony = wiersz.postponed_at is not None
    db.session.add(PriorityLog(
        action='zdjecie', order_id=wiersz.order_id, product_id=wiersz.product_id, station_code=station_code,
        new_value=unit_key_kafla, old_value='odlozone' if odlozony else wiersz.zrodlo,
        reason=wiersz.postpone_reason, note=wiersz.postpone_note, user_id=user_id,
        created_at=teraz or get_local_now()))
    wynik = {'unit_key': unit_key_kafla, 'order_id': wiersz.order_id, 'product_id': wiersz.product_id,
             'odlozony': odlozony}
    db.session.delete(wiersz)
    return wynik


# ══ Start stołów — kafle rozpoczęte (spec 5.8, ustalenie 17) ════════════════════════════════════════════════
#
# W chwili przejścia stanowisk na stoły system spisuje to, co na stanowisku jest już ZACZĘTE, i kładzie na stół
# (ponad K, `zrodlo='start'`) — żadne zamówienie, które ktoś ma w rękach, nie wypada z ekranu. Nowe kafle z kolejki
# wchodzą dopiero, gdy startowe zejdą poniżej K.
#
# „Rozpoczęte na stanowisku S” — ktoś ma to w rękach: pozycja CZEKA na S i ma już odbite sztuki (licznik
# `quantity_done_<S>` > 0). Decyzja Konrada 5.10 po bramce K3 (K3-poprawka-1): TYLKO licznik. Dawna druga reguła
# („inna pozycja zamówienia już zrobiona ręcznie na S”) dawała na kopii danych 53 z 74 kafli — Składanie 27 z 34
# pozycji, czyli praktycznie starą listę; resztę biuro dokłada „Wyślij” na podstawie podglądu.
#   * jednostka `pozycja`: pozycja w statusie S z licznikiem `quantity_done_<S>` > 0;
#   * jednostka `zamowienie`: zamówienie, które ma w statusie S pozycję z licznikiem > 0 — także niekompletne
#     (jak „Wyślij”);
#   * Pakowanie: także zamówienie bez sposobu dostawy (logistyka 4.6, spec 5.1).
# Źródła licznika nie sprawdzamy: stanowisko pominięte automatycznie (`auto_skip`, `system` w `complete_task`)
# dostaje licznik w tej samej chwili, w której pozycja z niego SCHODZI, więc pozycja czekająca na S z licznikiem S
# to praca z tabletu (na kopii danych warunek „ma zdarzenie ręczne” nie zmieniał ani jednego kafla).

def _licznik(pozycja, station_code):
    return getattr(pozycja, 'quantity_done_%s' % station_code, None) or 0


def _rozpoczete(station_code, jednostka, zamowienia):
    """
    Kafle rozpoczęte na stanowisku, policzone z wczytanych zamówień (odczyt bieżący albo zwykły — decyduje
    wołający): lista `(unit_key, zamówienie, pozycja | None, powód)` w kolejności (numer zamówienia, id pozycji).
    Powód jest jeden (`licznik`); pole zostaje w kontrakcie `GET /start`.
    """
    status = STATION_PENDING_STATUS[station_code]
    kafle = []
    for zamowienie in sorted(zamowienia, key=lambda z: (kolejka._klucz_numeru(z.internal_order_number), z.id)):
        zaczete = [p for p in sorted(zamowienie.products, key=lambda p: p.id)
                   if p.current_status == status and _licznik(p, station_code) > 0]
        if not zaczete:
            continue
        if jednostka == 'zamowienie':
            kafle.append((klucz_zamowienia(zamowienie.id), zamowienie, None, 'licznik'))
            continue
        kafle.extend((klucz_pozycji(pozycja.id), zamowienie, pozycja, 'licznik') for pozycja in zaczete)
    return kafle


def rozpoczete_na_stanowisku(station_code):
    """
    Podgląd startu stołów (spec 5.8 p. 1): kafle rozpoczęte na stanowisku — „to wejdzie na stół”. Same zwykłe
    odczyty, bez zapisu. Lista `{'unit_key', 'order_id', 'numer', 'product_id', 'short_id', 'powod', 'na_stole'}`;
    `powod`: zawsze `licznik` (pozycja z odbitymi sztukami — jedyna reguła od K3-poprawki-1);
    `na_stole` — kafel ma już wiersz stołu (leży albo jest odłożony), więc „Przygotuj stoły” go nie doda.
    """
    wymagaj_stolu(station_code)
    jednostka = ustawienia.jednostka(station_code)
    zamowienia, _pozycje = _odczyt_kandydatow(station_code, biezacy=False)
    na_stole = {wiersz.unit_key for wiersz in kafle(station_code, jednostka)}
    return [{'unit_key': klucz, 'order_id': zamowienie.id, 'numer': zamowienie.internal_order_number,
             'product_id': pozycja.id if pozycja is not None else None,
             'short_id': pozycja.short_product_id if pozycja is not None else None,
             'powod': powod, 'na_stole': klucz in na_stole}
            for klucz, zamowienie, pozycja, powod in _rozpoczete(station_code, jednostka, zamowienia)]


def przygotuj_start(station_code, user_id, *, teraz=None):
    """
    „Przygotuj stoły” dla jednego stanowiska (spec 5.8 p. 2): wpisuje kafle rozpoczęte jako wiersze stołu
    `zrodlo='start'` — ponad K. Stanowisko zwykle jest jeszcze w trybie `stary`: tablety stołu nie pokazują, a
    ZAKOŃCZ i tak zdejmuje kafel. Idempotentne: istniejących wierszy (na stole i odłożonych) nie rusza, dokłada
    tylko brakujące — kafel zdjęty ręcznie wróci, jeśli nadal jest rozpoczęty.

    Blokady jak dopełnianie: blokada stanowiska → zamówienia i pozycje odczytem bieżącym (FOR SHARE) → zwykły odczyt
    stołu → INSERT. Bez commita: router commituje TUŻ PRZED wywołaniem i po nim, każde stanowisko osobno. Zostawia
    w logu `start_stolow` (stanowisko, `new_value` = dodane, `old_value` = już leżały). Zwraca
    `{'dodane': n, 'juz_byly': m}`.
    """
    wymagaj_stolu(station_code)
    zablokuj_stanowisko(station_code)
    jednostka = ustawienia.jednostka(station_code)
    zamowienia, _pozycje = odczyt_biezacy_kandydatow(station_code)
    rozpoczete = _rozpoczete(station_code, jednostka, zamowienia)
    istniejace = {wiersz.unit_key for wiersz in kafle(station_code, jednostka)}
    teraz = teraz or get_local_now()
    dodane = 0
    for klucz, zamowienie, pozycja, _powod in rozpoczete:
        if klucz in istniejace:
            continue
        db.session.add(StationDesk(
            station_code=station_code, order_id=zamowienie.id, product_id=pozycja.id if pozycja is not None else None,
            unit_key=klucz, pulled_at=teraz, zrodlo=stale.ZRODLO_START, sent_by_user_id=user_id))
        dodane += 1
    juz_byly = len(rozpoczete) - dodane
    db.session.add(PriorityLog(action='start_stolow', station_code=station_code, new_value=str(dodane),
                               old_value=str(juz_byly), user_id=user_id, created_at=teraz))
    return {'dodane': dodane, 'juz_byly': juz_byly}
