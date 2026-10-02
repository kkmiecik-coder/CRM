# -*- coding: utf-8 -*-
"""
Stanowisko Dostawa (logistyka etap 4, krok 4.4, spec 9 i 4.5): przejścia trasy i jej przystanków — załadunek paczek,
„Zostaje”, zakończenie załadunku, wyjazd, dostarczenia, niedostarczenia, odhaczenie i cofnięcia. Wspólne dla telefonu
kierowcy (routers/dostawa_api.py) i panelu tras (routers/trasy_api.py). Funkcje NIE commitują.

KOLEJNOŚĆ BLOKAD każdego zapisu (zablokuj): blokada tras (routes.zablokuj_trasy — razem ze świeżą trasą i jej
przystankami) → blokada deklaracji paczek (paczki.zablokuj_deklaracje) → zamówienia FOR UPDATE rosnąco po id
(blokady_zamowien.zablokuj_zamowienia) → paczki i pozycje każdego zamówienia (paczki.zablokuj_stan) → dopiero
zapisy. Decyzje zapadają na odczycie bieżącym (REPEATABLE READ: migawka sprzed czekania na blokady jest nieświeża).
Blokada deklaracji jest potrzebna, bo zapis Dostawy czyta paczki odczytem blokującym (blokady luk indeksu
prod_packages), a deklaracja paczek wstawia nowe paczki w te luki: bez wspólnej blokady zakończenie załadunku
(wiele zamówień) i deklaracja na zamówieniu z tej samej trasy mogłyby się zakleszczyć. Nikt nie bierze blokady
deklaracji przed blokadą tras, więc ta para nie tworzy cyklu.

Każdy zapis blokuje zamówienia CAŁEJ trasy, nie tylko przystanku, którego dotyczy: telefon dostaje w odpowiedzi
pełną trasę (dostawa_widok.trasa_po_zapisie) i ma ona być bieżąca także dla pozostałych przystanków (dwa telefony
na jednej trasie). Zwykły odczyt po blokadach widziałby migawkę sprzed czekania na nie, a blokujący odczyt cudzych
paczek bez blokady ich zamówienia odwróciłby kolejność blokad (reguła unieważniania: zamówienie → paczki →
pozycje). Trasa robocza i zatwierdzona może jednak mieć zamówienia jeszcze w produkcji (dodanie do trasy i
zatwierdzenie nie wymagają spakowania), więc szersza blokada wstrzymuje na chwilę także stanowiska, doróbkę i Base.
tych zamówień. Pozycje wielu zamówień blokujemy w kolejności (zamówienie, id), a doróbka dokłada do starszego
zamówienia pozycję o wyższym id — z pisarzami wielu pozycji bez blokady zamówień, którzy piszą rosnąco po id
(przeliczenie i przeciąganie priorytetów, druk TCP), rzadkie zakleszczenie MySQL 1213 jest więc możliwe, jak w hurcie.
Zapisy Dostawy ponawiają się wtedy raz, od nowa i na nowym stanie (dostawa_api._zapis, trasy_api._akcja).

SILNE REFERENCJE (lekcja kroku 4.4a, przyczyna A): mapa tożsamości sesji trzyma czyste obiekty SŁABO. Wynik
zablokuj (trasa, {order_id: zamówienie}, {order_id: [paczki]}) każda funkcja trzyma w zmiennych lokalnych aż do
decyzji i zapisów, a decyzje zapadają wyłącznie na tych obiektach. Zamówienie zablokowane, którego nikt nie trzyma,
znikałoby z sesji (zamówienie i pozycje trzymają się tylko nawzajem), a późniejsze `ProductionOrder.query.get`
albo `order.products` czytałoby je od nowa zwykłym SELECT-em — na MySQL ze starej migawki.
"""
from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.models import LogisticsLog, Route, RouteStop
from modules.production.logistics.services import bl_sync, delivery, paczki, routes
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.logistics.services.weryfikacja import _notatka
from modules.production.models import ProductionOrder, ProductionPackage, ProductionProduct, get_local_now
from modules.production.services import blokady_zamowien

STANOWISKO = 'delivery'
METODY = ProductionPackage.SPOSOBY_POTWIERDZENIA   # ('skan', 'reczne')
POWODY_ZOSTAJE = {
    'niespakowane': u'Niespakowane',
    'niezweryfikowane': u'Niezweryfikowane',
    'brak_miejsca': u'Brak miejsca',
    'uszkodzone': u'Uszkodzone',
    'inne': u'Inne',
}
POWODY_NIEDOSTARCZENIA = {
    'brak_klienta': u'Brak klienta',
    'odmowa': u'Odmowa przyjęcia',
    'brak_dojazdu': u'Brak dojazdu',
    'uszkodzenie': u'Uszkodzenie',
    'inne': u'Inne',
}
# Przystanek odznaczony w oknie „Odhacz jako dostarczoną” panelu tras (spec 9.7) — tylko panel, nie telefon.
POWOD_ODHACZENIA = 'odhaczone_w_panelu'
ETYKIETA_ODHACZENIA = u'Odhaczone w panelu'
# Trasy, z których zamówienie nie wraca do produkcji bez zdjęcia z trasy (w Base. ma „Załadowane” albo „Wysłane”):
# hurt odmawia (products_api), doróbka i zmiana z Base. zdejmują (zdejmij_z_trasy_w_drodze), „Niedostarczone” zawsze
# wysyła 417343 (_wycofaj_z_trasy).
STATUSY_W_DRODZE = ('zaladowana', 'w_trasie')
# Powrót do produkcji z trasy w drodze (decyzja Konrada 2.10 A2, Ruling 30): powód we wpisie `niedostarczone` →
# (etykieta tego wpisu, notatka wpisu `trasa_usuniete`).
POWOD_DOROBKI = 'dorobka'
POWOD_ZMIANY_BASE = 'zmiana_base'
POWODY_POWROTU = {
    POWOD_DOROBKI: (u'Doróbka — wraca do produkcji', u'doróbka'),
    POWOD_ZMIANY_BASE: (u'Zmiana z Base. — wraca do produkcji', u'zmiana z Base.'),
}
# (U7, decyzja Konrada 2.10) Status 'wykonana' dla ludzi to „Dostarczona” — wartość w bazie i API zostaje. Słownik idzie
# też do telefonu kierowcy (dostawa_widok: `status_label`).
NAZWY_STATUSOW_TRASY = {'robocza': u'Robocza', 'zatwierdzona': u'Zatwierdzona', 'zaladowana': u'Załadowana',
                        'w_trasie': u'W trasie', 'wykonana': u'Dostarczona'}


class DostawaBlad(LogistykaBlad):
    """
    Odmowa Dostawy: `kod` dla appki (`error`), komunikat dla człowieka (`message`), `dane` — pola dodatkowe
    odpowiedzi (np. `braki`). Dziedziczy po LogistykaBlad, więc panel tras (trasy_api._odmowa) obsługuje ją bez zmian.
    """

    def __init__(self, kod, komunikat, status=409, dane=None):
        super().__init__(komunikat, status=status, dane=dane)
        self.kod = kod


def waliduj_powod(powod, slownik):
    """Powód z JSON-a. Typ sprawdzamy przed słownikiem (lista nie jest hashowalna), 422 jest zapamiętywane."""
    if not isinstance(powod, str) or powod not in slownik:
        raise DostawaBlad('invalid_reason', u'Powód: {}.'.format(u', '.join(sorted(slownik))), status=422)
    return powod


def waliduj_metode(metoda):
    """
    `skan` tylko wtedy, gdy pola nie ma (None), albo `reczne`. Każda inna wartość — także fałszywa z JSON-a (false,
    0, "", []) — to 422 invalid_method: 422 jest zapamiętywane, więc nie zgadujemy „skan” za appkę.
    """
    wynik = 'skan' if metoda is None else metoda
    if not isinstance(wynik, str) or wynik not in METODY:
        raise DostawaBlad('invalid_method', u'Sposób załadunku: „skan” albo „reczne”.', status=422)
    return wynik


def _numer(order):
    return order.internal_order_number or u'#{}'.format(order.id)


def _wymagaj_statusu(trasa, *statusy):
    if trasa.status not in statusy:
        raise DostawaBlad('route_status', u'Trasa „{}” jest {} — ta operacja nie jest dostępna.'.format(
            trasa.name, NAZWY_STATUSOW_TRASY.get(trasa.status, trasa.status).lower()))


def _przystanek(trasa, order_id):
    """Przystanek zamówienia na świeżej trasie (spod blokady) albo 404 stop_not_found."""
    stop = next((s for s in trasa.stops if s.order_id == order_id), None)
    if stop is None:
        raise DostawaBlad('stop_not_found', u'Tego zamówienia nie ma na trasie „{}”.'.format(trasa.name), status=404)
    return stop


def _zaladowane_na_trase(aktualne, trasa):
    """Aktualne paczki zamówienia załadowane na TĘ trasę."""
    return [p for p in aktualne if p.loaded_at is not None and p.loaded_route_id == trasa.id]


def _log_trasy(trasa, stary, nowy, teraz, user_id=None, worker_id=None, device_id=None):
    """Wpis `trasa_status` przy każdym przystanku świeżej trasy (wystarczy order_id — bez czytania zamówień)."""
    for s in trasa.stops:
        db.session.add(LogisticsLog(order_id=s.order_id, action='trasa_status', old_value=stary, new_value=nowy,
                                    route_id=trasa.id, user_id=user_id, worker_id=worker_id, device_id=device_id,
                                    created_at=teraz))


def zablokuj(route):
    """
    Blokady zapisu Dostawy w jednej kolejności (docstring modułu) dla wszystkich przystanków trasy. Zwraca (świeża
    trasa, {order_id: zamówienie}, {order_id: [aktualne paczki]}) — wszystko z odczytu bieżącego. Wołana drugi raz
    w tej samej transakcji (odpowiedź po zapisie) niczego nie czeka: blokady są już trzymane.

    Wołający trzyma całą krotkę w zmiennych lokalnych do końca decyzji i zapisów (silne referencje, docstring
    modułu) i decyduje tylko na tych obiektach: `order.products` to pozycje z odczytu bieżącego
    (blokady_zamowien.zablokuj_pozycje), paczki — z odczytu blokującego (paczki.zablokuj_stan).
    """
    try:
        trasa = routes.zablokuj_trasy(route)
    except LogistykaBlad as e:
        if e.status != 404:
            raise
        # Trasa skasowana (np. w panelu) między odczytem routera a blokadą — każda odmowa Dostawy ma kod dla appki.
        raise DostawaBlad('route_not_found', u'Nie ma takiej trasy.', status=404) from e
    paczki.zablokuj_deklaracje()
    zamowienia = {o.id: o for o in blokady_zamowien.zablokuj_zamowienia([s.order_id for s in trasa.stops])}
    pakunki = {order_id: paczki.zablokuj_stan(zamowienia[order_id]) for order_id in sorted(zamowienia)}
    return trasa, zamowienia, pakunki


def _paczka_niewazna():
    return DostawaBlad('package_void', u'Etykieta nieaktualna — paczki zadeklarowano ponownie.')


def _paczka_spoza_trasy(order_id, trasa):
    """
    409 package_not_on_route z nazwą trasy, na której jest zamówienie paczki, albo „bez trasy” (spec 9.3). Wołana
    pod trzymaną blokadą tras: przystanek i nazwę jego trasy czytamy odczytem bieżącym — zwykły odczyt widziałby
    migawkę sprzed czekania na blokadę (zamówienie przeniesione na inną trasę tuż przed skanem), a trasy założonej
    po migawce nie widziałby wcale. Zamówienia nie blokujemy (nie ma go na tej trasie, blokada odwróciłaby
    kolejność blokad); jego numer wewnętrzny się nie zmienia, więc tu zwykły odczyt wystarczy.
    """
    order = ProductionOrder.query.get(order_id)
    numer = _numer(order) if order is not None else u'#{}'.format(order_id)
    inna = routes.przystanek_zamowienia(order_id, aktualny=True)
    nazwa = None
    if inna is not None:
        nazwa = (db.session.query(Route.name).filter(Route.id == inna.route_id)
                 .with_for_update(read=True).scalar())
    gdzie = u'na trasie „{}”'.format(nazwa) if nazwa else u'bez trasy'
    return DostawaBlad('package_not_on_route', u'Paczka zamówienia {} nie jedzie trasą „{}” — zamówienie jest {}.'
                       .format(numer, trasa.name, gdzie), dane={'route_name': nazwa})


def _niezweryfikowane(order):
    return DostawaBlad('order_not_verified', u'Zamówienie {} nie jest zweryfikowane — na auto ładujemy tylko '
                       u'zweryfikowane paczki.'.format(_numer(order)))


def _anulowane(order):
    """Zamówienie bez aktywnych pozycji (anulowane w całości): ten sam kod co niezweryfikowane, własny komunikat."""
    return DostawaBlad('order_not_verified', u'Zamówienie {} jest anulowane — nie ładujemy.'.format(_numer(order)))


def _wiersz_paczki(package_id):
    """(order_id, voided_at) paczki zwykłym odczytem; brak paczki → 404 package_not_found."""
    wiersz = (db.session.query(ProductionPackage.order_id, ProductionPackage.voided_at)
              .filter(ProductionPackage.id == package_id).first())
    if wiersz is None:
        raise DostawaBlad('package_not_found', u'Nie ma paczki P-{}.'.format(package_id), status=404)
    return wiersz


def _wstepna_odmowa(route, wiersz):
    """
    Odmowa z migawki, PRZED blokadami (lekcja 1213 z kroku 4.3: nie czekamy na blokady, skoro i tak odmówimy).
    To tylko skrót: ostateczna decyzja zawsze zapada pod blokadami, na odczycie bieżącym, i sama sprawdza
    wszystko, co tu (test_odmowy_skanu_zapadaja_pod_blokadami). Migawka może się spóźniać o chwilę (weryfikacja
    zapisana tuż przed skanem): wtedy appka pokazuje odmowę, a ponowny skan przechodzi — 409 nie jest zapamiętywane.

    Co gwarantuje:
    - package_void, gdy paczka jest unieważniona w migawce. Unieważnienie się nie cofa, więc tej etykiety nie da
      się załadować nigdy. Kod może być inny niż pod blokadami (tam np. route_status na trasie już załadowanej),
      sam wynik — odmowa — nie.
    - order_not_verified tylko wtedy, gdy w migawce zamówienie paczki stoi na przystanku TEJ trasy, trasa jest
      zatwierdzona, przystanek nie ma „Zostaje”, a pozycje nie są wszystkie zweryfikowane (albo wszystkie są
      anulowane — wtedy komunikat „anulowane”). Pod blokadami te warunki sprawdzamy przed weryfikacją, więc
      przy stanie z migawki decyzja pod blokadami dałaby ten sam kod. W każdym innym przypadku (zamówienie na innej
      trasie albo bez trasy, trasa nie zatwierdzona, przystanek „Zostaje”) przepuszczamy: właściwy kod
      (package_not_on_route, route_status, stop_stays) daje decyzja pod blokadami — inaczej np. skan po
      zakończeniu załadunku mówiłby, że towar z auta „nie jest zweryfikowany”.
    """
    if wiersz.voided_at is not None:
        raise _paczka_niewazna()
    przystanek = (db.session.query(RouteStop.route_id, RouteStop.stays_reason, Route.status)
                  .join(Route, Route.id == RouteStop.route_id)
                  .filter(RouteStop.order_id == wiersz.order_id).first())
    if (przystanek is None or przystanek.route_id != route.id or przystanek.status != 'zatwierdzona'
            or przystanek.stays_reason):
        return
    statusy = [s for (s,) in db.session.query(ProductionProduct.current_status)
               .filter(ProductionProduct.order_id == wiersz.order_id,
                       ProductionProduct.current_status != 'anulowane')]
    if not statusy:
        raise _anulowane(ProductionOrder.query.get(wiersz.order_id))
    if any(s != 'zweryfikowane' for s in statusy):
        raise _niezweryfikowane(ProductionOrder.query.get(wiersz.order_id))


def zaladuj_paczke(route, package_id, metoda='skan', worker_id=None, device_id=None, teraz=None):
    """
    Skan albo ręczne odhaczenie paczki przy załadunku (spec 9.3). Zwraca (paczka, zmieniono). Trasa zatwierdzona,
    paczka ważna, jej zamówienie na TEJ trasie i zweryfikowane, przystanek bez „Zostaje” (inaczej 409 stop_stays —
    bez cichego zdejmowania oznaczenia). Ponowny skan = bez zmian. Pozycje zostają 'zweryfikowane' — 'zaladowane'
    dostają dopiero przy zakończeniu załadunku.

    `device_id` nie jest tu zapisywane: ślad w logu powstaje przy zakończeniu załadunku (plan).
    """
    metoda = waliduj_metode(metoda)
    wiersz = _wiersz_paczki(package_id)
    _wstepna_odmowa(route, wiersz)
    trasa, zamowienia, _pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zatwierdzona')
    order = zamowienia.get(wiersz.order_id)
    if order is None:
        raise _paczka_spoza_trasy(wiersz.order_id, trasa)
    stop = _przystanek(trasa, order.id)
    # Zamówienie paczki jest już zablokowane (zablokuj), więc odczyt blokujący samej paczki nie odwraca kolejności
    # blokad; widzi też unieważnienie zapisane po migawce.
    paczka = (ProductionPackage.query.filter(ProductionPackage.id == package_id)
              .with_for_update().populate_existing().one())
    if paczka.voided_at is not None:
        raise _paczka_niewazna()
    if stop.stays_reason:
        raise DostawaBlad('stop_stays', u'Zamówienie {} ma oznaczenie „Zostaje” ({}) — najpierw je zdejmij.'.format(
            _numer(order), POWODY_ZOSTAJE.get(stop.stays_reason, stop.stays_reason)))
    aktywne = delivery.aktywne_produkty(order)
    if not aktywne:
        raise _anulowane(order)
    if any(p.current_status != 'zweryfikowane' for p in aktywne):
        raise _niezweryfikowane(order)
    if paczka.loaded_at is not None and paczka.loaded_route_id == trasa.id:
        return paczka, False
    teraz = teraz or get_local_now()
    paczka.loaded_at = teraz
    paczka.loaded_by_worker_id = worker_id
    paczka.loaded_method = metoda
    paczka.loaded_route_id = trasa.id
    delivery.podbij_pozycje(order, teraz)   # ETag szczegółów trasy w telefonie i kolejek tabletów
    return paczka, True


def rozladuj_paczke(route, package_id, worker_id=None, device_id=None, teraz=None):
    """Cofnięcie pomyłki przed zakończeniem załadunku (spec 9.3). Zwraca (paczka, zmieniono); paczka niezaładowana
    na tę trasę → bez zmian. `worker_id` i `device_id` nie są tu zapisywane: ślad w logu powstaje przy zakończeniu
    załadunku (plan)."""
    wiersz = _wiersz_paczki(package_id)
    trasa, zamowienia, _pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zatwierdzona')
    order = zamowienia.get(wiersz.order_id)
    if order is None:
        raise _paczka_spoza_trasy(wiersz.order_id, trasa)
    paczka = (ProductionPackage.query.filter(ProductionPackage.id == package_id)
              .with_for_update().populate_existing().one())
    if paczka.loaded_at is None or paczka.loaded_route_id != trasa.id:
        return paczka, False
    paczki.wyczysc_zaladunek([paczka])
    delivery.podbij_pozycje(order, teraz or get_local_now())
    return paczka, True


def ustaw_zostaje(route, order_id, powod, notatka=None, worker_id=None, device_id=None, teraz=None):
    """
    „Zostaje” z powodem (spec 9.3) — przystanek zejdzie z trasy przy zakończeniu załadunku. Czyści znaczniki
    załadunku paczek zamówienia na tej trasie. Zwraca True, gdy coś zmieniła (ten sam powód i notatka — bez zmian).
    `worker_id` i `device_id` nie są tu zapisywane: ślad w logu (`zostaje`) powstaje przy zakończeniu załadunku
    (plan).
    """
    waliduj_powod(powod, POWODY_ZOSTAJE)
    notatka = _notatka(notatka)
    trasa, zamowienia, pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zatwierdzona')
    stop = _przystanek(trasa, order_id)
    zmieniono = (stop.stays_reason, stop.stays_note) != (powod, notatka)
    stop.stays_reason, stop.stays_note = powod, notatka
    if paczki.wyczysc_zaladunek(_zaladowane_na_trase(pakunki.get(order_id, []), trasa)):
        zmieniono = True
    if zmieniono and order_id in zamowienia:
        delivery.podbij_pozycje(zamowienia[order_id], teraz or get_local_now())
    return zmieniono


def zdejmij_zostaje(route, order_id, worker_id=None, device_id=None, teraz=None):
    """Zdjęcie „Zostaje” przed zakończeniem załadunku. Zwraca True, gdy przystanek je miał. `worker_id`
    i `device_id` nie są tu zapisywane: ślad w logu powstaje przy zakończeniu załadunku (plan)."""
    trasa, zamowienia, _pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zatwierdzona')
    stop = _przystanek(trasa, order_id)
    if stop.stays_reason is None and stop.stays_note is None:
        return False
    stop.stays_reason, stop.stays_note = None, None
    if order_id in zamowienia:
        delivery.podbij_pozycje(zamowienia[order_id], teraz or get_local_now())
    return True


def _opis_brakow(braki):
    numery = u', '.join(b['internal_order_number'] or u'#{}'.format(b['order_id']) for b in braki)
    return u'Nie wszystko jest załadowane: {} — załaduj paczki albo oznacz przystanek „Zostaje”.'.format(numery)


def zakoncz_zaladunek(route, worker_id=None, device_id=None, teraz=None):
    """
    „Zakończ załadunek” (spec 9.3). Każdy przystanek musi być załadowany (co najmniej jedna aktualna paczka, wszystkie
    załadowane na tę trasę, pozycje nadal 'zweryfikowane') albo mieć „Zostaje”; przystanek zamówienia anulowanego
    w całości schodzi z trasy sam. Braki → 409 loading_incomplete z listą `braki`; nic załadowanego → 409
    nothing_loaded (trasę, z której nic nie jedzie, logistyk cofa albo usuwa w panelu).

    Pod blokadami: „Zostaje” → zdjęcie z trasy (routes.usun_przystanek, log `zostaje` z powodem); anulowane →
    zdjęcie z trasy i wyczyszczenie znaczników załadunku jego paczek; załadowane → pozycje 'zaladowane', Base.
    524520 (dopychacz po commicie), log `zaladunek`; trasa → 'zaladowana', kto i kiedy.

    Zwraca (świeża trasa, usuniete):
    - załadunek zakończony teraz: `usuniete` = lista [{order_id, internal_order_number, reason}] (może być pusta);
    - trasa już 'zaladowana' albo 'w_trasie' (Ruling 23 — powtórka z kolejki offline z nowym X-Operation-Id):
      `usuniete` = None, bez żadnej zmiany i bez odmowy; router odpowiada 200 {changed: false, removed: []}.
    Inne statusy (robocza, wykonana) → 409 route_status.

    Zdejmowane zamówienia trzymają listy `zostaja` i `anulowane` (silne referencje), więc
    routes.usun_przystanek bierze je z mapy tożsamości (`query.get`) zamiast czytać od nowa z migawki.
    """
    trasa, zamowienia, pakunki = zablokuj(route)
    if trasa.status in ('zaladowana', 'w_trasie'):
        return trasa, None
    _wymagaj_statusu(trasa, 'zatwierdzona')
    braki, zostaja, anulowane, zaladowane = [], [], [], []
    for stop in list(trasa.stops):
        order = zamowienia.get(stop.order_id)
        if order is None:
            continue
        aktywne = delivery.aktywne_produkty(order)
        if not aktywne:
            anulowane.append(order)
            continue
        if stop.stays_reason:
            zostaja.append((stop.stays_reason, stop.stays_note, order))
            continue
        aktualne = pakunki.get(order.id, [])
        na_aucie = _zaladowane_na_trase(aktualne, trasa)
        wpis = {'order_id': order.id, 'internal_order_number': order.internal_order_number,
                'loaded': len(na_aucie), 'total': len(aktualne)}
        if not aktualne:
            braki.append(dict(wpis, reason='bez_paczek'))
        elif any(p.current_status != 'zweryfikowane' for p in aktywne):
            # Przed brakami załadunku: cofnięta weryfikacja czyści znaczniki załadunku, a kierowcy ważniejsze jest,
            # że tego zamówienia w ogóle nie załaduje (skan dostanie order_not_verified).
            braki.append(dict(wpis, reason='niezweryfikowane'))
        elif len(na_aucie) < len(aktualne):
            braki.append(dict(wpis, reason='niezaladowane'))
        else:
            zaladowane.append(order)
    if braki:
        raise DostawaBlad('loading_incomplete', _opis_brakow(braki), dane={'braki': braki})
    if not zaladowane:
        raise DostawaBlad('nothing_loaded', u'Na trasie „{}” nic nie jest załadowane — trasę, z której nic nie jedzie, '
                          u'cofnij albo usuń w panelu tras.'.format(trasa.name))
    teraz = teraz or get_local_now()
    usuniete = []
    for powod, notatka, order in zostaja:
        etykieta = POWODY_ZOSTAJE.get(powod, powod)
        delivery.zapisz_log(order, 'zostaje', None, powod,
                            note=(etykieta + (u': ' + notatka if notatka else u''))[:255],
                            route_id=trasa.id, worker_id=worker_id, device_id=device_id, teraz=teraz)
        usuniete.append({'order_id': order.id, 'internal_order_number': order.internal_order_number,
                         'reason': powod})
        routes.usun_przystanek(trasa, order.id, note=u'zostaje: ' + etykieta, wymagaj_roboczej=False,
                               worker_id=worker_id, device_id=device_id)
    for order in anulowane:
        usuniete.append({'order_id': order.id, 'internal_order_number': order.internal_order_number,
                         'reason': 'anulowane'})
        # Anulowane po skanie: paczki nie mogą zostać „na aucie” trasy, z której zamówienie schodzi (obiekty paczek
        # są już zablokowane — zablokuj).
        paczki.wyczysc_zaladunek(pakunki.get(order.id, []))
        routes.usun_przystanek(trasa, order.id, note=u'anulowane', wymagaj_roboczej=False,
                               worker_id=worker_id, device_id=device_id)
    trasa = routes.zablokuj_trasy(trasa)   # świeże przystanki po zdjęciach (ta sama transakcja, bez czekania)
    for order in zaladowane:
        for p in delivery.aktywne_produkty(order):
            p.current_status = 'zaladowane'
        bl_sync.oznacz_zaladowane(order)
        bl_sync.zaplanuj_po_commicie(order.id)
        delivery.zapisz_log(order, 'zaladunek', None, 'zaladowane', note=paczki.opis_paczek(pakunki[order.id]),
                            route_id=trasa.id, worker_id=worker_id, device_id=device_id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
    trasa.status = 'zaladowana'
    trasa.loaded_at = teraz
    trasa.loaded_by_worker_id = worker_id
    _log_trasy(trasa, 'zatwierdzona', 'zaladowana', teraz, worker_id=worker_id, device_id=device_id)
    return trasa, usuniete


def ruszaj(route, worker_id=None, device_id=None, teraz=None):
    """
    „Ruszam w trasę” (spec 9.4): trasa załadowana → w_trasie, kto i kiedy, Base. 149763 dla zamówień z pozycjami
    załadowanymi, log `wyjazd` (to on zapisuje tę zmianę statusu trasy — bez osobnego `trasa_status`). Trasa już
    w trasie albo wykonana (Ruling 23 — powtórka z kolejki offline, także po ostatnim dostarczeniu) → bez zmian
    i bez odmowy. Robocza i zatwierdzona → 409 route_status. Zwraca (trasa, zmieniono).

    Trasa załadowana bez przystanków (Ruling 30: doróbka albo zmiana z Base. zdjęła jedyny przystanek) → 409
    route_status: trasa w drodze bez przystanków nie zamknęłaby się sama — logistyk cofa załadunek albo odhacza ją.
    """
    trasa, zamowienia, _pakunki = zablokuj(route)
    if trasa.status in ('w_trasie', 'wykonana'):
        return trasa, False
    _wymagaj_statusu(trasa, 'zaladowana')
    if not trasa.stops:
        raise DostawaBlad('route_status', u'Trasa nie ma przystanków — logistyk cofnie załadunek albo odhaczy ją '
                                          u'w panelu tras.')
    teraz = teraz or get_local_now()
    trasa.status = 'w_trasie'
    trasa.departed_at = teraz
    trasa.departed_by_worker_id = worker_id
    for stop in trasa.stops:
        order = zamowienia.get(stop.order_id)
        if order is None:
            continue
        if any(p.current_status == 'zaladowane' for p in delivery.aktywne_produkty(order)):
            bl_sync.oznacz_wyslane(order)
            bl_sync.zaplanuj_po_commicie(order.id)
        delivery.zapisz_log(order, 'wyjazd', 'zaladowana', 'w_trasie', route_id=trasa.id, worker_id=worker_id,
                            device_id=device_id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
    return trasa, True


def cofnij_zaladunek(route, user_id=None, teraz=None):
    """
    „Cofnij załadunek” z panelu tras (spec 4.5, 9.7): trasa załadowana → zatwierdzona, pozycje 'zaladowane' →
    'zweryfikowane', znaczniki załadunku czyszczone, Base. 417343 dla zamówień, które były załadowane, log
    `zaladunek` (zaladowane → brak) i `trasa_status`. Zwraca świeżą trasę.
    """
    trasa, zamowienia, pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zaladowana')
    teraz = teraz or get_local_now()
    for stop in trasa.stops:
        order = zamowienia.get(stop.order_id)
        if order is None:
            continue
        cofniete = [p for p in delivery.aktywne_produkty(order) if p.current_status == 'zaladowane']
        for p in cofniete:
            p.current_status = 'zweryfikowane'
        paczki.wyczysc_zaladunek(pakunki.get(order.id, []))
        if cofniete:
            bl_sync.oznacz_planowana_trasa(order)
            bl_sync.zaplanuj_po_commicie(order.id)
            delivery.zapisz_log(order, 'zaladunek', 'zaladowane', None, note=u'cofnięty w panelu', route_id=trasa.id,
                                user_id=user_id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
    trasa.status = 'zatwierdzona'
    trasa.loaded_at = None
    trasa.loaded_by_worker_id = None
    _log_trasy(trasa, 'zaladowana', 'zatwierdzona', teraz, user_id=user_id)
    return trasa


# ── „Cofnij zatwierdzenie” w trakcie załadunku (panel tras, Ruling 21b kroku 4.4b) ─────────────────

NOTATKA_COFNIETEGO_ZATWIERDZENIA = u'cofnięte zatwierdzenie trasy'


def _ze_znacznikiem_trasy(aktualne, trasa):
    """Aktualne paczki zamówienia ze znacznikiem załadunku TEJ trasy (wystarczy sam `loaded_route_id`)."""
    return [p for p in aktualne if p.loaded_route_id == trasa.id]


def _sa_znaczniki_zaladunku(trasa):
    """
    Czy któraś aktualna paczka zamówienia z przystanku tej trasy ma znacznik załadunku tej trasy — zwykły odczyt
    (uzasadnienie w cofnij_zatwierdzenie). Tylko zamówienia z przystanków: tylko je zablokuj blokuje i czyści.
    """
    ids = [s.order_id for s in trasa.stops]
    if not ids:
        return False
    return db.session.query(ProductionPackage.id).filter(
        ProductionPackage.order_id.in_(ids), ProductionPackage.loaded_route_id == trasa.id,
        ProductionPackage.voided_at.is_(None)).first() is not None


def cofnij_zatwierdzenie(route, user_id=None, teraz=None):
    """
    „Cofnij zatwierdzenie” z panelu tras: trasa zatwierdzona → robocza (routes.cofnij_do_roboczej, np. przed
    zastępstwem kierowcy — decyzja Konrada 5). Kierowca mógł już zacząć ładować: paczki mają wtedy znacznik
    załadunku tej trasy, a pozycje są jeszcze 'zweryfikowane' ('zaladowane' dostają dopiero przy zakończeniu
    załadunku). Takie znaczniki czyścimy pod blokadami Dostawy (zablokuj — kolejność z docstringu modułu), z logiem
    `zaladunek` (zaladowane → brak, notatka „cofnięte zatwierdzenie trasy”) i podbiciem pozycji (ETag kolejek
    i szczegółów trasy w telefonie) — inaczej zostałyby na paczkach także wtedy, gdy przystanek trafi potem na inną
    trasę. Bez znaczników — jak dotąd: sama blokada tras, bez blokad zamówień. Zwraca świeżą trasę.

    Flagi „Zostaje” przystanków tej trasy też znikają (runda 1 zadania 4): powrót do roboczej to nowy załadunek
    od zera, a zastępca kierowcy (decyzja 5) nie dziedziczy cudzych decyzji. Log `zostaje` (powód → brak, ta sama
    notatka) przy przystanku, któremu coś zdjęto. Flagi leżą na przystankach, które blokada tras czyta odczytem
    bieżącym, więc ich zdjęcie nie wymaga blokad zamówień.

    Sprawdzenie znaczników to zwykły odczyt. Znaczniki tej trasy zakłada tylko załadunek (zaladuj_paczke), a ten
    bierze blokadę tras — dlatego router (trasy_api.route_revert) zaczyna transakcję od nowa tuż przed tą blokadą
    (panel_api._zapis_pod_blokada): migawka powstaje już pod blokadą i widzi każdy zacommitowany załadunek.
    Znaczniki czyści też (bez blokady tras) cofnięcie weryfikacji i reguła unieważniania etapów: gdy migawka pokaże
    znacznik już wyczyszczony, decyzja pod blokadami (odczyt bieżący) niczego nie zapisze.
    """
    teraz = teraz or get_local_now()
    trasa = routes.zablokuj_trasy(route)
    zablokowane = None
    if trasa.status == 'zatwierdzona' and _sa_znaczniki_zaladunku(trasa):
        # Silne referencje (docstring modułu): krotka zablokuj zostaje w zmiennych do końca zapisów.
        trasa, zamowienia, pakunki = zablokuj(trasa)
        for order_id in sorted(zamowienia):
            order = zamowienia[order_id]
            if not paczki.wyczysc_zaladunek(_ze_znacznikiem_trasy(pakunki.get(order_id, []), trasa)):
                continue
            delivery.zapisz_log(order, 'zaladunek', 'zaladowane', None, note=NOTATKA_COFNIETEGO_ZATWIERDZENIA,
                                route_id=trasa.id, user_id=user_id, teraz=teraz)
            delivery.podbij_pozycje(order, teraz)
        zablokowane = [zamowienia[s.order_id] for s in trasa.stops if s.order_id in zamowienia]
    if trasa.status == 'zatwierdzona':
        _zdejmij_flagi_zostaje(trasa, user_id, teraz)
    # Dotychczasowa logika na trasie spod blokady (status, kto i kiedy, log `trasa_status`, podbicie pozycji) — ze
    # znacznikami na zamówieniach z zablokuj, bez zwykłego odczytu zamówień po blokadach (Ruling P2).
    routes.cofnij_do_roboczej(trasa, user_id=user_id, zamowienia=zablokowane)
    return trasa


def _zdejmij_flagi_zostaje(trasa, user_id, teraz):
    """Flagi „Zostaje” przystanków świeżej trasy (spod blokady tras) → brak, log `zostaje` przy każdym zdjętym."""
    for s in trasa.stops:
        if s.stays_reason is None and s.stays_note is None:
            continue
        # Sam order_id przystanku — bez czytania zamówień (jak _log_trasy).
        db.session.add(LogisticsLog(order_id=s.order_id, action='zostaje', old_value=(s.stays_reason or None),
                                    new_value=None, note=NOTATKA_COFNIETEGO_ZATWIERDZENIA, route_id=trasa.id,
                                    user_id=user_id, created_at=teraz))
        s.stays_reason, s.stays_note = None, None


# ── Dostarczenia (trasa w drodze) i odhaczenie z panelu ─────────────────────────────────────────────

def _rozliczona(trasa, zamowienia):
    """
    Każdy przystanek dostarczony albo zamówienia anulowanego w całości (trasa bez przystanków też — kierowca wrócił ze
    wszystkim). Przystanek anulowanego (fala końcowa 4.4b, C2): klient anulował w Base. po zakończeniu załadunku —
    liczniki kierowcy i panelu liczą tylko przystanki aktywne („dostarczono 2/2”), więc trasa zamyka się po ostatnim
    realnym dostarczeniu zamiast wisieć w drodze. `zamowienia` — zamówienia zablokowane przez wołającego
    ({order_id: zamówienie}); przystanek zamówienia spoza tej mapy liczy się tylko po `delivered_at`.
    """
    def anulowane(order_id):
        order = zamowienia.get(order_id)
        return order is not None and not delivery.aktywne_produkty(order)

    return all(s.delivered_at is not None or anulowane(s.order_id) for s in trasa.stops)


def _zamknij_jesli_rozliczona(trasa, teraz, zamowienia=None, user_id=None, worker_id=None, device_id=None):
    """
    Spec 9.5: brak nierozliczonych przystanków → trasa 'wykonana'. `completed_by` zostaje NULL — zamknął telefon
    (albo zdjęcie po powrocie do produkcji), więc kierowca może jeszcze cofnąć ostatnie dostarczenie (decyzja
    Konrada 3). Zwraca True, gdy zamknęła. `zamowienia` — zablokowane zamówienia trasy (_rozliczona).
    """
    if trasa.status != 'w_trasie' or not _rozliczona(trasa, zamowienia or {}):
        return False
    trasa.status, trasa.completed_at, trasa.completed_by = 'wykonana', teraz, None
    _log_trasy(trasa, 'w_trasie', 'wykonana', teraz, user_id=user_id, worker_id=worker_id, device_id=device_id)
    return True


NOTATKA_DOSTARCZENIA_ZOSTAJE = u'oznaczone jako dostarczone'


def _oznacz_dostarczone(order, stop, teraz, user_id=None, worker_id=None, device_id=None):
    """
    Pozycje aktywne → 'dostarczone', przystanek z kto i kiedy, Base. 149778, log `dostarczone`, zamknięcie.

    `delivered_by_worker_id` = kierowca z telefonu albo NULL z panelu (odhaczenie) — po nim telefon rozpoznaje
    dostarczenie zaznaczone w panelu, którego sam nie cofa (cofnij_dostarczenie, C4). Flaga „Zostaje” przystanku
    znika (C3: „Odhacz” z trasy zatwierdzonej może zaznaczyć przystanek z decyzją kierowcy „Zostaje”) — inaczej po
    „Cofnij dostarczenie” trasa w drodze pokazywałaby „Zostaje”, którego nie da się już zdjąć; ślad w logu `zostaje`
    (powód → brak), jak przy cofnięciu zatwierdzenia.
    """
    aktywne = delivery.aktywne_produkty(order)
    stare = u','.join(sorted({p.current_status for p in aktywne}))[:64]
    for p in aktywne:
        p.current_status = 'dostarczone'
    stop.delivered_at = teraz
    stop.delivered_by_worker_id = worker_id
    _zdejmij_zostaje_dostarczonego(stop, teraz, user_id=user_id, worker_id=worker_id, device_id=device_id)
    bl_sync.oznacz_dostarczone(order)
    bl_sync.zaplanuj_po_commicie(order.id)
    delivery.zapisz_log(order, 'dostarczone', stare, 'dostarczone', route_id=stop.route_id, user_id=user_id,
                        worker_id=worker_id, device_id=device_id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    delivery.przelicz_zamkniecie(order, teraz)


def _zdejmij_zostaje_dostarczonego(stop, teraz, user_id=None, worker_id=None, device_id=None):
    """C3: flaga „Zostaje” przystanku oznaczanego jako dostarczony → brak, z wpisem `zostaje` (tylko gdy była)."""
    if stop.stays_reason is None and stop.stays_note is None:
        return
    # Sam order_id przystanku — bez czytania zamówienia (jak _log_trasy).
    db.session.add(LogisticsLog(order_id=stop.order_id, action='zostaje', old_value=(stop.stays_reason or None),
                                new_value=None, note=NOTATKA_DOSTARCZENIA_ZOSTAJE, route_id=stop.route_id,
                                user_id=user_id, worker_id=worker_id, device_id=device_id, created_at=teraz))
    stop.stays_reason, stop.stays_note = None, None


def _wycofaj_z_trasy(trasa, order, aktualne, powod, notatka, teraz, user_id=None, worker_id=None, device_id=None):
    """
    „Niedostarczone” (telefon) i przystanek odznaczony przy odhaczeniu (panel), spec 4.5: zamówienie wraca do puli
    „Transport bez trasy” — pozycje 'zaladowane' → 'zweryfikowane', znaczniki załadunku czyszczone, Base. 417343,
    zdjęcie z trasy (routes.usun_przystanek: log `trasa_usuniete` z notatką „niedostarczone” jak w etapie 3
    i przeliczenie zamknięcia), log `niedostarczone` z powodem.

    Base. 417343 (Ruling 30): zawsze z trasy załadowanej albo w drodze — Base. ma wtedy „Załadowane” albo „Wysłane”,
    także gdy pozycje cofnęła wcześniej zmiana z Base. albo dawny hurt (spójnie z doróbką), poza zamówieniem
    anulowanym w całości (Base. ma status anulowania — nie nadpisujemy go); z trasy roboczej i zatwierdzonej — tylko,
    gdy było załadowane (zamówienie z trasy zatwierdzonej ma 417343 od spakowania).

    Ruling 25 (A): zamówienie bez weryfikacji (`verified_at` NULL — trasa odhaczona bez załadunku, potem cofnięte
    dostarczenie dało 'zaladowane') wraca do 'spakowane', nie 'zweryfikowane': „zweryfikowane” bez weryfikacji
    ominęłoby bramkę załadunku.

    Log `niedostarczone` idzie PO zdjęciu z trasy, więc jest ostatnim wpisem zamówienia — po nim nie_dostarcz
    rozpoznaje powtórkę z kolejki offline (Ruling 26, _powtorka_niedostarczenia).
    """
    wraca = 'zweryfikowane' if order.verified_at is not None else 'spakowane'
    cofniete = [p for p in delivery.aktywne_produkty(order) if p.current_status == 'zaladowane']
    for p in cofniete:
        p.current_status = wraca
    paczki.wyczysc_zaladunek(aktualne)
    if cofniete or (trasa.status in STATUSY_W_DRODZE and delivery.aktywne_produkty(order)):
        bl_sync.oznacz_planowana_trasa(order)
        bl_sync.zaplanuj_po_commicie(order.id)
    routes.usun_przystanek(trasa, order.id, user_id=user_id, note=u'niedostarczone', wymagaj_roboczej=False,
                           worker_id=worker_id, device_id=device_id)
    etykieta = ETYKIETA_ODHACZENIA if powod == POWOD_ODHACZENIA else POWODY_NIEDOSTARCZENIA.get(powod, powod)
    delivery.zapisz_log(order, 'niedostarczone', None, powod,
                        note=(etykieta + (u': ' + notatka if notatka else u''))[:255], route_id=trasa.id,
                        user_id=user_id, worker_id=worker_id, device_id=device_id, teraz=teraz)


def _ostatnie_niedostarczenie(trasa, order_id):
    """
    Wartość (powód) OSTATNIEGO wpisu logu zamówienia, gdy to `niedostarczone` z TEJ trasy, inaczej None.
    `_wycofaj_z_trasy` i `zdejmij_z_trasy_w_drodze` piszą ten wpis jako ostatni (po zdjęciu przystanku). Wąsko:
    zamówienie, którego na trasie nie było, niedostarczone z innej trasy albo zmienione potem (np. dodane do nowej
    trasy) → None.

    Odczyt BIEŻĄCY (fala końcowa 4.4b, C1): blokada współdzielona na ostatnim wpisie i luce za nim. Wołamy pod
    trzymanymi blokadami tras, deklaracji i zamówień trasy (zablokuj). Wpisy logu zamówienia zapisują tylko
    posiadacze blokady tras (trasy, Dostawa, panel Logistyki) albo blokady tego zamówienia (Weryfikacja, deklaracja
    paczek, reguła unieważniania, hurt, doróbka, cron): co zatwierdzili przed nami, widzimy (zwykły SELECT pokazałby
    migawkę sprzed czekania na blokady — w wyścigu z „Odhacz”, drugim telefonem albo zdublowanym X-Operation-Id
    kierowca dostawał 404 zamiast 200 bez zmian), a nowszy wpis tego zamówienia czeka na luce do naszego commitu.
    Bez cyklu: po tym odczycie zapis Dostawy na nic już nie czeka (powtórka — odpowiedź bez zapisów, inaczej odmowa
    404), więc nikt, kto czeka na nasze wpisy, nie może czekać w kółko.
    """
    ostatni = (db.session.query(LogisticsLog.action, LogisticsLog.route_id, LogisticsLog.new_value)
               .filter(LogisticsLog.order_id == order_id)
               .order_by(LogisticsLog.id.desc()).with_for_update(read=True).first())
    if ostatni is None or ostatni.action != 'niedostarczone' or ostatni.route_id != trasa.id:
        return None
    return ostatni.new_value


def _powtorka_niedostarczenia(trasa, order_id):
    """
    Ruling 26: brak przystanku to skutek udanego „Niedostarczone” z TEJ trasy (także spóźnionego po odznaczeniu
    w panelu, po doróbce i po zmianie z Base.) — ostatni wpis logu zamówienia to `niedostarczone` z tej trasy
    (_ostatnie_niedostarczenie).
    """
    return _ostatnie_niedostarczenie(trasa, order_id) is not None


def _brak_przystanku_dostarczenia(trasa, order_id):
    """
    404 stop_not_found dla „Dostarczone” bez przystanku. C5 (fala końcowa 4.4b): kierowca potwierdził dostarczenie
    offline, a logistyk w tym czasie odhaczył trasę i odznaczył ten przystanek — kod bez zmian (appka klasyfikuje go
    jak dotąd), ale komunikat mówi, co się stało, zamiast „Tego zamówienia nie ma na trasie”. Tak samo po zdjęciu
    z trasy w drodze przez doróbkę albo zmianę z Base. (Ruling 30).
    """
    powod = _ostatnie_niedostarczenie(trasa, order_id)
    if powod == POWOD_ODHACZENIA:
        return DostawaBlad('stop_not_found', u'Logistyk zdjął to zamówienie z trasy w panelu.', status=404)
    if powod in POWODY_POWROTU:
        return DostawaBlad('stop_not_found', u'Zamówienie wróciło do produkcji i zostało zdjęte z trasy.', status=404)
    return DostawaBlad('stop_not_found', u'Tego zamówienia nie ma na trasie „{}”.'.format(trasa.name), status=404)


def dostarcz(route, order_id, worker_id=None, device_id=None, teraz=None):
    """
    „Dostarczone” na przystanku (spec 9.5). Zwraca (trasa, zmieniono, zamknieta). Wszystkie aktywne pozycje muszą być
    'zaladowane' — zamówienie, które wróciło do produkcji albo zostało anulowane w trakcie jazdy, dostaje 409
    order_status (kierowca rozlicza je „Niedostarczone”). Ostatni rozliczony przystanek zamyka trasę. Przystanek już
    dostarczony = bez zmian (powtórka z kolejki offline), także na trasie, którą to dostarczenie zamknęło. Brak
    przystanku → 404 stop_not_found (komunikat: _brak_przystanku_dostarczenia).
    """
    trasa, zamowienia, _pakunki = zablokuj(route)
    stop = next((s for s in trasa.stops if s.order_id == order_id), None)
    if stop is None:
        raise _brak_przystanku_dostarczenia(trasa, order_id)
    if stop.delivered_at is not None:
        return trasa, False, False
    _wymagaj_statusu(trasa, 'w_trasie')
    order = zamowienia.get(order_id)
    aktywne = delivery.aktywne_produkty(order) if order is not None else []
    if not aktywne or any(p.current_status != 'zaladowane' for p in aktywne):
        numer = _numer(order) if order is not None else u'#{}'.format(order_id)
        raise DostawaBlad('order_status', u'Zamówienie {} nie jest załadowane — wróciło do produkcji albo zostało '
                          u'anulowane. Rozlicz przystanek jako „Niedostarczone”.'.format(numer))
    teraz = teraz or get_local_now()
    _oznacz_dostarczone(order, stop, teraz, worker_id=worker_id, device_id=device_id)
    return trasa, True, _zamknij_jesli_rozliczona(trasa, teraz, zamowienia, worker_id=worker_id,
                                                  device_id=device_id)


def nie_dostarcz(route, order_id, powod, notatka=None, worker_id=None, device_id=None, teraz=None):
    """
    „Niedostarczone” z powodem (spec 9.5 i 4.5) — patrz _wycofaj_z_trasy. Przystanek dostarczony → 409
    stop_delivered (najpierw cofnij dostarczenie). Ostatni rozliczony przystanek zamyka trasę. Zwraca
    (trasa, zmieniono, zamknieta).

    Powtórka (Ruling 26 — kolejka offline z nowym X-Operation-Id po udanym zdjęciu przystanku): przystanku już nie
    ma, a ostatni wpis logu zamówienia to niedostarczenie z tej trasy → (trasa, False, False), bez zmian i bez
    odmowy, także na trasie, którą to niedostarczenie zamknęło. Każdy inny brak przystanku → 404 stop_not_found.
    """
    waliduj_powod(powod, POWODY_NIEDOSTARCZENIA)
    notatka = _notatka(notatka)
    trasa, zamowienia, pakunki = zablokuj(route)
    if not any(s.order_id == order_id for s in trasa.stops) and _powtorka_niedostarczenia(trasa, order_id):
        return trasa, False, False
    stop = _przystanek(trasa, order_id)
    _wymagaj_statusu(trasa, 'w_trasie')
    if stop.delivered_at is not None:
        raise DostawaBlad('stop_delivered', u'Przystanek jest już dostarczony — najpierw cofnij dostarczenie.')
    teraz = teraz or get_local_now()
    _wycofaj_z_trasy(trasa, zamowienia[order_id], pakunki.get(order_id, []), powod, notatka, teraz,
                     worker_id=worker_id, device_id=device_id)
    trasa = routes.zablokuj_trasy(trasa)   # świeże przystanki po zdjęciu (ta sama transakcja, bez czekania)
    return trasa, True, _zamknij_jesli_rozliczona(trasa, teraz, zamowienia, worker_id=worker_id,
                                                  device_id=device_id)


# ── Powrót do produkcji z trasy załadowanej albo w drodze (decyzja Konrada 2.10 A2, Ruling 30) ────────────

def blokady_trasy_w_drodze(order_id):
    """
    Pierwszy krok doróbki i zmiany z Base. po globalnej blokadzie tras, PRZED blokadą zamówienia. Gdy przystanek
    zamówienia jest niedostarczony na trasie załadowanej albo w drodze — blokady Dostawy CAŁEJ trasy (zablokuj:
    trasa → deklaracje paczek → zamówienia rosnąco → paczki → pozycje) i ich wynik (trasa, {order_id: zamówienie},
    {order_id: [paczki]}); wołający bierze swoje zamówienie z tej mapy zamiast blokować je osobno. Inaczej None —
    wołający blokuje samo zamówienie, jak dotąd.

    Dlaczego cała trasa: zdjęcie z trasy w drodze może ją zamknąć, a zamknięcie decyduje na zamówieniach pozostałych
    przystanków (przystanek anulowanego w całości jest rozliczony — C2) i zapisuje przy nich `trasa_status` (wpis z FK
    do zamówienia). Blokada tych zamówień PO własnym zamówieniu odwróciłaby kolejność rosnącą crona logistyki — dlatego
    wszystkie w kolejności Dostawy, zanim zapis sięgnie po cokolwiek innego.

    Przystanek i status trasy czytamy jednym odczytem BLOKUJĄCYM kolumn (bez obiektów ORM i bez leniwego dociągania
    trasy): pod blokadą tras piszą je tylko jej posiadacze, a żaden zwykły odczyt nie zakłada tu migawki REPEATABLE READ
    przed blokadami zamówień (zmiana z Base. czyta potem zwykłymi zapytaniami pozycje pod blokadą zamówienia).
    """
    wiersz = (db.session.query(RouteStop.route_id, RouteStop.delivered_at, Route.status)
              .join(Route, Route.id == RouteStop.route_id)
              .filter(RouteStop.order_id == order_id)
              .with_for_update(read=True).first())
    if wiersz is None or wiersz.delivered_at is not None or wiersz.status not in STATUSY_W_DRODZE:
        return None
    return zablokuj(wiersz.route_id)


def zdejmij_z_trasy_w_drodze(blokady, order, powod, teraz, user_id=None, worker_id=None, device_id=None):
    """
    Zamówienie z trasy załadowanej albo w drodze, które wróciło do produkcji (doróbka — decyzja Konrada 2.10 A2;
    zmiana z Base., np. nowa pozycja — Ruling 30), schodzi z trasy jak przy „Niedostarczone”. Pozycje idą do produkcji
    jak dotąd (regułę unieważniania etapów wołający woła wcześniej: 'zaladowane' → 'spakowane', paczki unieważnione,
    weryfikacja skasowana). Tu: znaczniki załadunku czyszczone, Base. 417343 „Planowana trasa” — bez warunku, bo w Base.
    wisi „Załadowane” albo „Wysłane” także wtedy, gdy pozycje cofnięto wcześniej — przystanek zdjęty
    (routes.usun_przystanek, log `trasa_usuniete` z notatką powodu), a na końcu log `niedostarczone` z powodem
    (`dorobka`, `zmiana_base`) jako ostatni wpis zamówienia: spóźnione „Niedostarczone” z kolejki telefonu jest wtedy
    powtórką (Ruling 26), a spóźnione „Dostarczone” dostaje jasny komunikat (_brak_przystanku_dostarczenia). Zdjęcie
    ostatniego nierozliczonego przystanku trasy w drodze zamyka ją, jak „Niedostarczone” (z C2 — na zablokowanych
    zamówieniach wszystkich przystanków). Zwraca nazwę trasy, z której zdjęto, albo None.

    `blokady` — wynik blokady_trasy_w_drodze (wołający trzyma go do końca zapisu — silne referencje). Zamówienie, które
    NIE wróciło do produkcji (wszystkie aktywne pozycje spakowane lub dalej, np. zmiana ilości z Base.; anulowane
    w całości), zostaje na trasie — None. NIE commituje.
    """
    trasa, zamowienia, _pakunki = blokady
    aktywne = delivery.aktywne_produkty(order)
    if not any(p.current_status not in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne):
        return None
    etykieta, notatka = POWODY_POWROTU[powod]
    # Zamówienie, paczki i pozycje są już zablokowane (zablokuj) — tu tylko odczyt bieżący aktualnych paczek.
    paczki.wyczysc_zaladunek(paczki.zablokuj_stan(order))
    bl_sync.oznacz_planowana_trasa(order)
    bl_sync.zaplanuj_po_commicie(order.id)
    routes.usun_przystanek(trasa, order.id, user_id=user_id, note=notatka, wymagaj_roboczej=False,
                           worker_id=worker_id, device_id=device_id)
    delivery.zapisz_log(order, 'niedostarczone', None, powod, note=etykieta, route_id=trasa.id, user_id=user_id,
                        worker_id=worker_id, device_id=device_id, teraz=teraz)
    trasa = routes.zablokuj_trasy(trasa)   # świeże przystanki po zdjęciu (ta sama transakcja, bez czekania)
    _zamknij_jesli_rozliczona(trasa, teraz, zamowienia, user_id=user_id, worker_id=worker_id, device_id=device_id)
    return trasa.name


def cofnij_dostarczenie(route, order_id, z_telefonu=False, user_id=None, worker_id=None, device_id=None,
                        teraz=None):
    """
    „Cofnij dostarczenie” (spec 4.5): pozycje 'dostarczone' → 'zaladowane', przystanek bez kto i kiedy, Base. 149763,
    log `dostarczenie_cofniete`, zamówienie znów otwarte; trasa wykonana wraca do 'w_trasie'. Przystanek
    niedostarczony = bez zmian (powtórka). Zwraca (trasa, zmieniono).

    Panel: dowolny dostarczony przystanek trasy w drodze albo wykonanej, bez sprawdzania zajętości pojazdu
    i kierowcy (korekta, nie planowanie). Telefon (`z_telefonu`): tylko ostatnie dostarczenie (najpóźniejsze
    `delivered_at`, przy remisie dalszy przystanek), także zaraz po automatycznym zamknięciu trasy (decyzja Konrada 3
    — trasa zamknięta telefonem ma `completed_by` NULL); trasę odhaczoną w panelu cofa tylko panel. Tak samo
    pojedyncze dostarczenie zaznaczone w panelu (`delivered_by_worker_id` NULL — C4 fali końcowej 4.4b): po „Cofnij
    dostarczenie” w panelu trasa wraca do „w trasie” z `completed_by` NULL, ale pozostałe przystanki odhaczone przez
    logistyka telefon dalej omija (409 route_status).
    Na trasie odhaczonej bez załadunku (z roboczej albo zatwierdzonej) cofnięcie też daje 'zaladowane' i 'w_trasie'
    (spec 4.5) — logistyk rozlicza potem przystanek ponownym „Odhacz”.
    """
    trasa, zamowienia, _pakunki = zablokuj(route)
    stop = _przystanek(trasa, order_id)
    if stop.delivered_at is None:
        return trasa, False
    _wymagaj_statusu(trasa, 'w_trasie', 'wykonana')
    if z_telefonu:
        if trasa.status == 'wykonana' and trasa.completed_by is not None:
            raise DostawaBlad('route_status', u'Trasę „{}” odhaczono w panelu tras — dostarczenie cofnie tam '
                              u'logistyk.'.format(trasa.name))
        if stop.delivered_by_worker_id is None:
            raise DostawaBlad('route_status', u'To dostarczenie zaznaczył logistyk w panelu — cofnąć może tylko '
                              u'panel.')
        ostatni = max((s for s in trasa.stops if s.delivered_at is not None),
                      key=lambda s: (s.delivered_at, s.position))
        if ostatni.order_id != order_id:
            raise DostawaBlad('not_last_delivery', u'Telefon cofa tylko ostatnie dostarczenie na trasie — starsze '
                              u'cofnie logistyk w panelu tras.')
    teraz = teraz or get_local_now()
    order = zamowienia.get(order_id)
    if order is not None:
        cofniete = [p for p in delivery.aktywne_produkty(order) if p.current_status == 'dostarczone']
        for p in cofniete:
            p.current_status = 'zaladowane'
        if cofniete:
            bl_sync.oznacz_wyslane(order)
            bl_sync.zaplanuj_po_commicie(order.id)
            # Wpis tylko, gdy któraś pozycja się zmieniła: przystanek zamówienia anulowanego w całości (odhaczony
            # bez statusu Base.) traci sam znacznik dostarczenia, bez „dostarczone → zaladowane” w historii.
            delivery.zapisz_log(order, 'dostarczenie_cofniete', 'dostarczone', 'zaladowane', route_id=trasa.id,
                                user_id=user_id, worker_id=worker_id, device_id=device_id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
        delivery.przelicz_zamkniecie(order, teraz)
    stop.delivered_at = None
    stop.delivered_by_worker_id = None
    if trasa.status == 'wykonana':
        trasa.status, trasa.completed_at, trasa.completed_by = 'w_trasie', None, None
        _log_trasy(trasa, 'wykonana', 'w_trasie', teraz, user_id=user_id, worker_id=worker_id, device_id=device_id)
    return trasa, True


def _odmowa_niespakowanych(zamowienia, niespakowane):
    numery = u', '.join(zamowienia[i].internal_order_number or u'#{}'.format(i) for i in niespakowane)
    if len(niespakowane) == 1:
        tekst = (u'Zamówienie {} nie jest jeszcze w całości spakowane — spakuj je na tablecie '
                 u'albo odznacz, a wróci do puli bez trasy.')
    else:
        tekst = (u'Zamówienia {} nie są jeszcze w całości spakowane — spakuj je na tablecie '
                 u'albo odznacz, a wrócą do puli bez trasy.')
    return LogistykaBlad(tekst.format(numery), status=409, dane={'niespakowane': niespakowane})


def odhacz(route, dostarczone_ids, user_id=None, teraz=None):
    """
    „Odhacz jako dostarczoną” z panelu tras (spec 9.7; dostępne też z roboczej — ruling R12 etapu 3). Zastępuje
    routes.wykonaj z etapu 3. `dostarczone_ids` (WYMAGANE, także pusta lista — M6) to zamówienia dostarczone;
    przystanki dostarczone już z telefonu zostają dostarczone. Zaznaczone → jak „Dostarczone” (pozycje
    'dostarczone', Base. 149778); odznaczone → jak „Niedostarczone” z powodem `odhaczone_w_panelu`. (I1) 409 z
    `niespakowane`, gdy jako dostarczone zaznaczono zamówienie, którego aktywne pozycje nie są wszystkie spakowane
    (lub dalej); zamówienia bez aktywnych pozycji ta reguła pomija. Trasa → 'wykonana', completed_by = użytkownik
    (telefon nie cofa wtedy ostatniego dostarczenia). Zwraca {'dostarczone', 'niedostarczone'} w kolejności
    przystanków.

    Trasa bez przystanków: robocza i zatwierdzona → 422 (logistyk ją usuwa albo uzupełnia). Załadowaną albo w drodze
    (Ruling 30: doróbka albo zmiana z Base. zdjęła jedyny przystanek, a „Ruszam” takiej trasy odmawia) „Odhacz”
    zamyka jako dostarczoną (status 'wykonana') — z pustą listą dostarczonych; zapis tylko na trasie (bez wpisów logu,
    bo nie ma zamówień,
    i bez Base.).
    """
    trasa, zamowienia, pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, *routes.AKTYWNE)
    na_trasie = [s.order_id for s in trasa.stops]
    if not na_trasie and trasa.status not in STATUSY_W_DRODZE:
        raise LogistykaBlad(u'Trasa nie ma przystanków.', status=422)
    if dostarczone_ids is None:
        raise LogistykaBlad(u'Podaj listę dostarczonych zamówień (delivered_order_ids), '
                            u'także pustą.', status=422)
    zaznaczone = set(routes._lista_id(dostarczone_ids))
    if not zaznaczone <= set(na_trasie):
        raise LogistykaBlad(u'Część zamówień nie należy do tej trasy.', status=422)
    juz = {s.order_id for s in trasa.stops if s.delivered_at is not None}
    dostarczone = zaznaczone | juz
    nowe = [i for i in na_trasie if i in dostarczone and i not in juz]
    niespakowane = [i for i in nowe if i in zamowienia and delivery.aktywne_produkty(zamowienia[i])
                    and not delivery.wszystkie_spakowane(zamowienia[i])]
    if niespakowane:
        raise _odmowa_niespakowanych(zamowienia, niespakowane)
    teraz = teraz or get_local_now()
    niedostarczone = [i for i in na_trasie if i not in dostarczone]
    for order_id in niedostarczone:
        _wycofaj_z_trasy(trasa, zamowienia[order_id], pakunki.get(order_id, []), POWOD_ODHACZENIA, None, teraz,
                         user_id=user_id)
    trasa = routes.zablokuj_trasy(trasa)   # świeże przystanki po zdjęciach
    stary = trasa.status
    for stop in trasa.stops:
        if stop.order_id not in nowe:
            continue
        order = zamowienia.get(stop.order_id)
        if order is not None and delivery.aktywne_produkty(order):
            _oznacz_dostarczone(order, stop, teraz, user_id=user_id)
        else:
            # Anulowane w całości — bez statusu Base. Też dostarczenie z panelu (C4: kierowca NULL), bez „Zostaje”.
            stop.delivered_at, stop.delivered_by_worker_id = teraz, None
            _zdejmij_zostaje_dostarczonego(stop, teraz, user_id=user_id)
            if order is not None:
                # Jak dawne routes.wykonaj: anulowane, którego anulowanie ominęło przeliczenie, zamyka się od razu.
                delivery.przelicz_zamkniecie(order, teraz)
    trasa.status, trasa.completed_at, trasa.completed_by = 'wykonana', teraz, user_id
    _log_trasy(trasa, stary, 'wykonana', teraz, user_id=user_id)
    return {'dostarczone': [i for i in na_trasie if i in dostarczone], 'niedostarczone': niedostarczone}
