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
pozycje). Zamówienia z trasy zatwierdzonej i dalej nie mają już pracy stanowisk, więc szersza blokada nikogo
realnie nie wstrzymuje (Base. i doróbka czekają kilka milisekund).

SILNE REFERENCJE (lekcja kroku 4.4a, przyczyna A): mapa tożsamości sesji trzyma czyste obiekty SŁABO. Wynik
zablokuj (trasa, {order_id: zamówienie}, {order_id: [paczki]}) każda funkcja trzyma w zmiennych lokalnych aż do
decyzji i zapisów, a decyzje zapadają wyłącznie na tych obiektach. Zamówienie zablokowane, którego nikt nie trzyma,
znikałoby z sesji (zamówienie i pozycje trzymają się tylko nawzajem), a późniejsze `ProductionOrder.query.get`
albo `order.products` czytałoby je od nowa zwykłym SELECT-em — na MySQL ze starej migawki.
"""
from extensions import db
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
# Przystanek odznaczony w oknie „Odhacz jako wykonaną” panelu tras (spec 9.7) — tylko panel, nie telefon.
POWOD_ODHACZENIA = 'odhaczone_w_panelu'
ETYKIETA_ODHACZENIA = u'Odhaczone w panelu'
NAZWY_STATUSOW_TRASY = {'robocza': u'Robocza', 'zatwierdzona': u'Zatwierdzona', 'zaladowana': u'Załadowana',
                        'w_trasie': u'W trasie', 'wykonana': u'Wykonana'}


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
    """`skan` (domyślnie) albo `reczne`; inaczej 422 invalid_method."""
    wynik = metoda or 'skan'
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
    trasa = routes.zablokuj_trasy(route)
    paczki.zablokuj_deklaracje()
    zamowienia = {o.id: o for o in blokady_zamowien.zablokuj_zamowienia([s.order_id for s in trasa.stops])}
    pakunki = {order_id: paczki.zablokuj_stan(zamowienia[order_id]) for order_id in sorted(zamowienia)}
    return trasa, zamowienia, pakunki


def _paczka_niewazna():
    return DostawaBlad('package_void', u'Etykieta nieaktualna — paczki zadeklarowano ponownie.')


def _paczka_spoza_trasy(order_id, trasa):
    """
    409 package_not_on_route z nazwą trasy, na której jest zamówienie paczki, albo „bez trasy” (spec 9.3). Zwykłe
    odczyty wystarczą: to tylko treść odmowy, a zamówienia spoza trasy nie blokujemy (odwróciłoby to kolejność
    blokad).
    """
    order = ProductionOrder.query.get(order_id)
    numer = _numer(order) if order is not None else u'#{}'.format(order_id)
    inna = routes.przystanek_zamowienia(order_id)
    nazwa = inna.route.name if inna is not None else None
    gdzie = u'na trasie „{}”'.format(nazwa) if nazwa else u'bez trasy'
    return DostawaBlad('package_not_on_route', u'Paczka zamówienia {} nie jedzie trasą „{}” — zamówienie jest {}.'
                       .format(numer, trasa.name, gdzie), dane={'route_name': nazwa})


def _niezweryfikowane(order):
    return DostawaBlad('order_not_verified', u'Zamówienie {} nie jest zweryfikowane — na auto ładujemy tylko '
                       u'zweryfikowane paczki.'.format(_numer(order)))


def _wiersz_paczki(package_id):
    """(order_id, voided_at) paczki zwykłym odczytem; brak paczki → 404 package_not_found."""
    wiersz = (db.session.query(ProductionPackage.order_id, ProductionPackage.voided_at)
              .filter(ProductionPackage.id == package_id).first())
    if wiersz is None:
        raise DostawaBlad('package_not_found', u'Nie ma paczki P-{}.'.format(package_id), status=404)
    return wiersz


def _wstepna_odmowa(route, wiersz):
    """
    Odmowa z migawki, PRZED blokadami (lekcja 1213 z kroku 4.3: nie czekamy na blokady, skoro i tak odmówimy):
    paczka unieważniona (to się nie cofa) albo zamówienie z TEJ trasy, które w migawce nie jest zweryfikowane.
    Paczkę zamówienia spoza tej trasy przepuszczamy — odmowa z nazwą jego trasy zapada pod blokadami. Migawka może
    się spóźniać o chwilę (weryfikacja zapisana tuż przed skanem): wtedy appka pokazuje odmowę, a ponowny skan
    przechodzi — 409 nie jest zapamiętywane.

    Sprawdzenia idą w tej samej kolejności co decyzja pod blokadami: trasa, która w migawce nie jest zatwierdzona,
    nie dostaje odmowy „niezweryfikowane” — pod blokadami dostanie route_status. Inaczej skan po zakończeniu
    załadunku (pozycje już 'zaladowane') mówiłby kierowcy, że towar z auta „nie jest zweryfikowany”.
    """
    if wiersz.voided_at is not None:
        raise _paczka_niewazna()
    przystanek = (db.session.query(RouteStop.route_id, Route.status)
                  .join(Route, Route.id == RouteStop.route_id)
                  .filter(RouteStop.order_id == wiersz.order_id).first())
    if przystanek is None or przystanek.route_id != route.id or przystanek.status != 'zatwierdzona':
        return
    statusy = [s for (s,) in db.session.query(ProductionProduct.current_status)
               .filter(ProductionProduct.order_id == wiersz.order_id,
                       ProductionProduct.current_status != 'anulowane')]
    if not statusy or any(s != 'zweryfikowane' for s in statusy):
        raise _niezweryfikowane(ProductionOrder.query.get(wiersz.order_id))


def zaladuj_paczke(route, package_id, metoda='skan', worker_id=None, device_id=None, teraz=None):
    """
    Skan albo ręczne odhaczenie paczki przy załadunku (spec 9.3). Zwraca (paczka, zmieniono). Trasa zatwierdzona,
    paczka ważna, jej zamówienie na TEJ trasie i zweryfikowane, przystanek bez „Zostaje” (inaczej 409 stop_stays —
    bez cichego zdejmowania oznaczenia). Ponowny skan = bez zmian. Pozycje zostają 'zweryfikowane' — 'zaladowane'
    dostają dopiero przy zakończeniu załadunku.
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
    if not aktywne or any(p.current_status != 'zweryfikowane' for p in aktywne):
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
    na tę trasę → bez zmian."""
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
    """Zdjęcie „Zostaje” przed zakończeniem załadunku. Zwraca True, gdy przystanek je miał."""
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

    Pod blokadami: „Zostaje” → zdjęcie z trasy (routes.usun_przystanek, log `zostaje` z powodem); załadowane →
    pozycje 'zaladowane', Base. 524520 (dopychacz po commicie), log `zaladunek`; trasa → 'zaladowana', kto i kiedy.
    Zwraca (świeża trasa, usuniete: [{order_id, internal_order_number, reason}]).

    Zdejmowane zamówienia trzymają listy `zostaja` i `anulowane` (silne referencje), więc
    routes.usun_przystanek bierze je z mapy tożsamości (`query.get`) zamiast czytać od nowa z migawki.
    """
    trasa, zamowienia, pakunki = zablokuj(route)
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
    w trasie → bez zmian (powtórka z kolejki offline). Zwraca (trasa, zmieniono).
    """
    trasa, zamowienia, _pakunki = zablokuj(route)
    if trasa.status == 'w_trasie':
        return trasa, False
    _wymagaj_statusu(trasa, 'zaladowana')
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
