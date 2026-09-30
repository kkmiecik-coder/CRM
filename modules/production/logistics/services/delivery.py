# -*- coding: utf-8 -*-
"""
Cykl życia zamówienia w logistyce (spec, sekcje 6.2 i 6.4).

Funkcje NIE commitują — robi to wołający (router, model, cron), żeby zmiana
sposobu dostawy, przepakowanie i log szły w jednej transakcji.
"""
import re

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.models import LogisticsLog, Route, RouteStop, STATUSY_TRASY_AKTYWNE
from modules.production.models import get_local_now

# Pozycja „zeszła z produkcji”: czeka na pakowanie albo jest spakowana lub dalej (logistyka etap 4).
STATUSY_PO_PRODUKCJI = ('czeka_na_pakowanie',) + sposoby.STATUSY_PO_SPAKOWANIU


class LogistykaBlad(Exception):
    """
    Odmowa z komunikatem dla człowieka. status = kod HTTP (409 stan, 422 dane).
    `dane` — dodatkowe pola odpowiedzi JSON obok `error` (np. `niespakowane` z odhaczenia
    trasy, routes.wykonaj), żeby interfejs nie musiał wyczytywać ich z tekstu komunikatu.
    """

    def __init__(self, komunikat, status=409, dane=None):
        super().__init__(komunikat)
        self.komunikat = komunikat
        self.status = status
        self.dane = dane or {}


def aktywne_produkty(order):
    return [p for p in order.products if p.current_status != 'anulowane']


def wszystkie_w(order, statusy):
    """Czy zamówienie ma aktywną (niezanulowaną) pozycję i każda aktywna jest w `statusy`."""
    aktywne = aktywne_produkty(order)
    return bool(aktywne) and all(p.current_status in statusy for p in aktywne)


def wszystkie_spakowane(order):
    """
    „Spakowane lub dalej” (logistyka etap 4, spec 4.1): towar całego zamówienia jest spakowany —
    także zweryfikowany, załadowany albo dostarczony. Tak pytają lista (plakietka „spakowane”),
    routes.wykonaj (odhaczenie trasy) i sam delivery (po_spakowaniu, zmiana sposobu dostawy).
    Kto potrzebuje DOKŁADNIE 'spakowane'
    (deklaracja paczek), woła wszystkie_w(order, ('spakowane',)).
    """
    return wszystkie_w(order, sposoby.STATUSY_PO_SPAKOWANIU)


def zapisz_log(order, akcja, stara=None, nowa=None, user_id=None, note=None,
               route_id=None, teraz=None, worker_id=None, device_id=None):
    db.session.add(LogisticsLog(
        order_id=order.id, action=akcja, old_value=stara, new_value=nowa,
        user_id=user_id, worker_id=worker_id, device_id=device_id, note=note,
        route_id=route_id, created_at=teraz or get_local_now()))


def podbij_pozycje(order, teraz):
    """ETag kolejek tabletów liczy się z MAX(updated_at) pozycji — bez tego tablet dostanie 304."""
    for p in order.products:
        p.updated_at = teraz


def zamkniecie_wyliczone(order, trasa=None):
    """
    Tabela z sekcji 6.2 specu. Transport własny zamyka dopiero trasa wykonana (etap 3).

    `trasa` — (resztka O1; Task 1, runda 4.1: też routes.usun_przystanek) świeża trasa, na
    której leży (albo leżał) przystanek zamówienia, podana przez routes.wykonaj/przywroc/
    usun_przystanek: odczytana pod blokadą tras, z przystankami już po zmianie w tej
    transakcji. Wtedy decyduje ona, a nie routes.przystanek_zamowienia — zwykły odczyt z
    migawki transakcji sprzed blokady mógłby nie zobaczyć przystanku dodanego tuż przed nią
    (zamówienie zostałoby otwarte do crona); `trasa` daje ten sam stan bez nowego zwykłego
    odczytu przystanków (reguła: po blokadzie tylko świeża `route.stops`). Bez `trasa` (cron,
    products_api, zmiana sposobu) — zwykły odczyt jak dotąd: ci wołający nie trzymają blokady
    tras, więc odczyt blokujący odwróciłby kolejność blokad (wiersz blokady zawsze pierwszy).
    """
    aktywne = aktywne_produkty(order)
    if not aktywne:
        return True
    sposob = sposoby.normalizuj(order.override_delivery_method)
    if sposob is None or order.repack_required:
        return False
    if sposob == sposoby.KURIER:
        # Kurier kończy cykl po spakowaniu; weryfikacja nie może go z powrotem otworzyć.
        return all(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne)
    if sposob == sposoby.ODBIOR:
        return order.handed_over_at is not None
    # Transport własny: koniec cyklu = przystanek na trasie wykonanej (etap 3).
    if trasa is not None:
        # Zamówienie jest na co najwyżej jednej trasie (UNIQUE order_id) — nie ma go na tej,
        # to nie ma go na żadnej.
        return trasa.status == 'wykonana' and any(s.order_id == order.id for s in trasa.stops)
    from modules.production.logistics.services import routes
    przystanek = routes.przystanek_zamowienia(order.id)
    return przystanek is not None and przystanek.route.status == 'wykonana'


def przelicz_zamkniecie(order, teraz=None, trasa=None):
    """Ustawia albo czyści logistics_closed_at. Zwraca True, gdy stan się zmienił.
    `trasa` — patrz zamkniecie_wyliczone (tylko routes.wykonaj/przywroc/usun_przystanek)."""
    zamkniete = zamkniecie_wyliczone(order, trasa=trasa)
    if zamkniete and order.logistics_closed_at is None:
        order.logistics_closed_at = teraz or get_local_now()
        return True
    if not zamkniete and order.logistics_closed_at is not None:
        order.logistics_closed_at = None
        return True
    return False


def odnotuj_wejscie_do_pakowania(order, teraz):
    """„Zeszło z produkcji” (Arkusz): chwila, gdy OSTATNI aktywny produkt wszedł do pakowania."""
    if order.logistics_completed_at is not None:
        return
    aktywne = aktywne_produkty(order)
    if aktywne and all(p.current_status in STATUSY_PO_PRODUKCJI for p in aktywne):
        order.logistics_completed_at = teraz


def po_spakowaniu(order, teraz):
    """Wołane z complete_task('packaging'). Kończy przepakowanie i przelicza cykl."""
    if wszystkie_spakowane(order):
        # Zaległe 138620 z przepakowania nie może nadpisać statusu po spakowaniu,
        # który właśnie wysyła ścieżka pakowania (baselinker_status_sync).
        # NIEZALEŻNIE od flagi przepakowania: kurier (przepakowanie, 138620) →
        # z powrotem transport kasuje flagę, a znacznik 138620 zostaje.
        if order.bl_status_pending_id == sposoby.STATUS_PRODUKCJA_ZAKONCZONA:
            order.bl_status_pending_id = None
        if order.repack_required or order.repack_reason:
            order.repack_required = False
            order.repack_reason = None
            podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)


def _przystanek_do_zmiany(order, zdejmuje, opis):
    """
    (etap 3) Przystanek zamówienia i blokady zmian na trasach. Trasa wykonana —
    zamówienie dostarczone, żadnych zmian. Zatwierdzona — zmiana, która zdejmuje
    zamówienie z trasy albo zmienia adres (`zdejmuje=True`), wymaga cofnięcia
    zatwierdzenia (eksport do Routimo mógł już pójść). Zwraca przystanek albo None.

    (fix-1, Ruling A6) Odczyt BIEŻĄCY przystanku i blokada globalna PRZED odczytem
    statusu trasy — zwykły SELECT czytałby migawkę sprzed blokady i mógłby przepuścić
    zmianę na trasie, którą ktoś inny właśnie zatwierdził albo wykonał w międzyczasie.
    Blokada spada tu PRZED pierwszym zapisem `zmien_adres`/`ustaw_sposob_dostawy`
    (obaj wołają to jako pierwszą rzecz po odczytach) — patrz routes.zablokuj_trasy().

    (fix-2, N1) Blokada globalna (bez `route` — nie znamy go, dopóki nie znajdziemy
    przystanku) MUSI być PIERWSZĄ rzeczą tutaj, PRZED odczytem przystanku poniżej.
    Każdy piszący trasę bierze blokady w kolejności: wiersz blokady → trasa i jej
    przystanki (`zablokuj_trasy`). Gdyby ta funkcja najpierw czytała przystanek
    (biorąc współdzieloną blokadę na jego wierszu, albo na luce UNIQUE, gdy
    zamówienia nie ma jeszcze na trasie) i dopiero potem sięgała po wiersz blokady,
    kolejność byłaby odwrotna — a dwie odwrotne kolejności blokad na dwóch
    transakcjach to podręcznikowy zakleszczenie (MySQL 1213): ta funkcja czeka na
    wiersz blokady trzymany przez piszącego trasę, a piszący trasę czeka na wiersz
    przystanku/lukę trzymaną przez tę funkcję. Dotyczy adresu (`zmien_adres`),
    zmiany sposobu dostawy (`ustaw_sposob_dostawy`) i pinezki mapy
    (`sprawdz_trase_przed_zmiana` z `geocoding.ustaw_recznie`/`resetuj`).
    """
    from modules.production.logistics.services import routes
    routes.zablokuj_trasy()
    przystanek = routes.przystanek_zamowienia(order.id, aktualny=True)
    if przystanek is None:
        return None
    trasa = routes.zablokuj_trasy(przystanek.route)
    if trasa.status == 'wykonana':
        raise LogistykaBlad(u'Zamówienie {} zostało dostarczone trasą „{}”.'.format(
            order.internal_order_number, trasa.name))
    if trasa.status == 'zatwierdzona' and zdejmuje:
        raise LogistykaBlad(u'Zamówienie {} jest na zatwierdzonej trasie „{}” — najpierw cofnij '
                            u'jej zatwierdzenie, potem {}.'.format(order.internal_order_number,
                                                                   trasa.name, opis))
    return przystanek


def sprawdz_trase_przed_zmiana(order, opis):
    """
    (fix-1) Wejście publiczne do `_przystanek_do_zmiany` dla wołających spoza tego
    modułu — ręczna korekta i reset pinezki mapy (`geocoding.ustaw_recznie`/
    `resetuj`) to też „zmiana”, którą trasa zatwierdzona blokuje: eksport do
    Routimo (spec 8.4) mógł już pójść z bieżącym punktem (spec 10). `_przystanek_do_zmiany`
    zostaje prywatny (wołany też z `ustaw_sposob_dostawy`/`zmien_adres` w TYM
    module) — to jedyny publiczny, udokumentowany sposób odwołania się doń z
    zewnątrz, zamiast każdy wołający sięgał po nazwę z podkreśleniem. Nic nie
    zwraca — sam wyjątek (409, ten sam wzorzec komunikatu co adres) jest efektem,
    o który chodzi wołającemu.
    """
    _przystanek_do_zmiany(order, True, opis)


def _zdejmij_z_trasy(przystanek, order, user_id):
    from modules.production.logistics.services import routes
    nazwa = przystanek.route.name
    routes.usun_przystanek(przystanek.route, order.id, user_id=user_id,
                           note=u'zmiana sposobu dostawy')
    return nazwa


def ustaw_sposob_dostawy(order, sposob, user_id=None, teraz=None):
    """
    `sposob` = jeden z sposoby.SPOSOBY albo sposoby.BRAK („Nie ustawiono”) — cofnięcie
    pomyłki logistyka. Samo None / pusty tekst NIE cofa (to raczej zgubione pole
    formularza niż decyzja), tylko daje 422 jak nieznana wartość.
    """
    cofniecie = sposob == sposoby.BRAK
    nowy = None if cofniecie else sposoby.normalizuj(sposob)
    if nowy is None and not cofniecie:
        raise LogistykaBlad(u'Nieznany sposób dostawy: {}'.format(sposob), status=422)
    if order.handed_over_at is not None:
        raise LogistykaBlad(u'Zamówienie {} zostało już wydane klientowi.'.format(
            order.internal_order_number))
    if not aktywne_produkty(order):
        raise LogistykaBlad(u'Zamówienie {} jest anulowane.'.format(order.internal_order_number))

    stary = sposoby.normalizuj(order.override_delivery_method)
    if stary == nowy:
        return {'zmieniono': False, 'przepakowanie': False, 'usunieto_z_trasy': None}
    # (etap 4) Towar na aucie albo u klienta — nowy sposób dostawy wysłałby do Base. status po
    # spakowaniu i cofnął „Załadowane”/„Wysłane”/„Dostarczona”. Po porównaniu bez zmian, jak przesyłka.
    if any(p.current_status in ('zaladowane', 'dostarczone') for p in aktywne_produkty(order)):
        raise LogistykaBlad(u'Zamówienie {} jest już załadowane albo dostarczone — sposobu dostawy '
                            u'nie zmieniamy.'.format(order.internal_order_number))
    # (M3) Przesyłka już utworzona (kurier mógł ją odebrać) — zmiana sposobu wysłałaby do
    # Base. status nowego sposobu (np. 149777 „Czeka na odbiór”) zamiast statusu wysyłki.
    # Jak adres (zmien_adres). Po porównaniu bez zmian: ten sam sposób zostaje no-opem.
    # (rereview, „New Breakage”) Odmowa tylko, gdy jest co odwoływać: stary sposób już
    # ustawiony (Base. dostał metodę dostawy do zmiany) albo towar w całości spakowany
    # (przesyłka mogła już pojechać). PIERWSZE ustawienie (stary=None) przy niespakowanym
    # towarze przechodzi — inaczej stare zamówienie z polami przesyłki po dawnej stacji
    # wysyłki (sprzed 11.08), które wróciło do produkcji bez sposobu dostawy, utykałoby na
    # zawsze: tablet żąda sposobu (409 delivery_method_not_set), a panel odmawiałby go ustawić.
    if (order.shipping_package_id or order.shipping_tracking_number) and (
            stary is not None or wszystkie_spakowane(order)):
        raise LogistykaBlad(u'Zamówienie {} ma już utworzoną przesyłkę — sposób dostawy zmień '
                            u'u kuriera i w Base.'.format(order.internal_order_number))

    zdejmuje = nowy != sposoby.TRANSPORT   # kurier, odbiór i cofnięcie (nowy=None) zdejmują z trasy
    przystanek = _przystanek_do_zmiany(order, zdejmuje, u'zmień sposób dostawy')

    teraz = teraz or get_local_now()
    if cofniecie:
        if any(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne_produkty(order)):
            # Przegląd K1: po cofnięciu kolejny wybór nie wiedziałby, pod jaki sposób
            # pakowano (stary = None), więc „transport (spakowane) → brak → kurier”
            # ominęłoby przepakowanie i zamknęło zamówienie. Przy spakowanym towarze
            # logistyk wybiera od razu właściwy sposób — zmiana na kuriera sama cofnie
            # towar do przepakowania.
            raise LogistykaBlad(
                u'Zamówienie {} jest już spakowane — nie da się cofnąć do „Nie ustawiono”. '
                u'Wybierz od razu właściwy sposób dostawy.'.format(order.internal_order_number))
        usunieto = _zdejmij_z_trasy(przystanek, order, user_id) if przystanek is not None else None
        wynik = _cofnij_sposob(order, stary, user_id, teraz)
        wynik['usunieto_z_trasy'] = usunieto
        return wynik
    order.override_delivery_method = nowy
    order.delivery_method_set_at = teraz
    order.delivery_method_set_by = user_id
    zapisz_log(order, 'sposob_dostawy', stary, nowy, user_id=user_id, teraz=teraz)

    spakowane = [p for p in aktywne_produkty(order)
                 if p.current_status in sposoby.STATUSY_PO_SPAKOWANIU]
    przepakowanie = (nowy == sposoby.KURIER
                     and stary in (sposoby.TRANSPORT, sposoby.ODBIOR)
                     and bool(spakowane))
    nowy_status = False
    if przepakowanie:
        order.repack_required = True
        for p in spakowane:
            # Zdarzenie systemowe bez atrybucji: cofnięcie spakowania nie jest
            # niczyją pracą, a statystyki pierwotnego pakowacza zostają.
            p.set_quantity_done('packaging', 0, source='system')
            p.packaging_completed_at = None
            p.current_status = 'czeka_na_pakowanie'
        if all(p.current_status in STATUSY_PO_PRODUKCJI for p in aktywne_produkty(order)):
            order.bl_status_pending_id = sposoby.STATUS_PRODUKCJA_ZAKONCZONA
            nowy_status = True
        zapisz_log(order, 'przepakowanie', stary, nowy, user_id=user_id, teraz=teraz)
        order.repack_reason = sposoby.PRZEPAKUJ_NA_KURIERA
        # Jedna reguła (spec 4.5): zamówienie wróciło do pakowania — paczki i weryfikacja kasują się.
        from modules.production.logistics.services import weryfikacja
        weryfikacja.uniewaznij_etapy(order, teraz, u'przepakowanie na kuriera', user_id=user_id)
    elif wszystkie_spakowane(order):
        order.bl_status_pending_id = sposoby.STATUS_PO_SPAKOWANIU[nowy]
        nowy_status = True

    if (not nowy_status
            and order.bl_status_pending_id in sposoby.STATUS_PO_SPAKOWANIU.values()
            and not wszystkie_spakowane(order)):
        # Niewysłany jeszcze status po spakowaniu poprzedniego sposobu (np. 149777
        # „Czeka na odbiór”), a zamówienie nie jest już w całości spakowane (Base.
        # dołożył pozycję, przepakowanie) — dopychacz wysłałby nieaktualny status.
        # Właściwy status po spakowaniu wyśle ścieżka pakowania, gdy wszystko się spakuje.
        order.bl_status_pending_id = None

    if (order.delivery_method or '').strip() != sposoby.TEKST_BASE[nowy]:
        order.bl_delivery_method_pending = True

    if nowy != sposoby.KURIER:
        # Zmiana na sposób inny niż kurier zamyka ewentualne przepakowanie:
        # towar już wrócił do pakowania i po prostu się pakuje, baner
        # „PRZEPAKUJ NA KURIERA” dla transportu/odbioru nie ma sensu.
        _zdejmij_baner_przepakowania_na_kuriera(order)

    usunieto_z_trasy = None
    if przystanek is not None and zdejmuje:
        usunieto_z_trasy = _zdejmij_z_trasy(przystanek, order, user_id)

    podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)
    return {'zmieniono': True, 'przepakowanie': przepakowanie, 'usunieto_z_trasy': usunieto_z_trasy}


def _zdejmij_baner_przepakowania_na_kuriera(order):
    """
    Zmiana sposobu dostawy zdejmuje TYLKO baner „Przepakuj na kuriera” (także stare repack_required
    bez tekstu): przy innym sposobie takie przepakowanie traci sens. Baner z Weryfikacji („Weryfikacja:
    Uszkodzenie: …”, krok 4.3) zostaje — to informacja dla pakowacza o towarze, a nie o kurierze;
    czyści go dopiero ponowne spakowanie (po_spakowaniu).
    """
    if not order.repack_reason or order.repack_reason == sposoby.PRZEPAKUJ_NA_KURIERA:
        order.repack_required = False
        order.repack_reason = None


def _cofnij_sposob(order, stary, user_id, teraz):
    """
    Powrót do „Nie ustawiono” — logistyk wybrał sposób nie temu zamówieniu.

    Base.: niewysłaną jeszcze metodę i status po spakowaniu kasujemy (decyzja,
    której dotyczyły, już nie obowiązuje). Metody, która do Base. już poszła, nie
    „odwołujemy” — Base. nie ma pustej metody dostawy; logistyk ustawi właściwy
    sposób i ten nadpisze ją przy następnej wysyłce. Tak samo zostaje status po
    spakowaniu, który już poszedł do Base. Wołana tylko, gdy nic nie jest spakowane
    (patrz ustaw_sposob_dostawy). Tablet: pozycje, które nie są
    jeszcze spakowane, znów blokują pakowanie (409 delivery_method_not_set), a
    zamówienie wraca na listę otwartych (przelicz_zamkniecie).
    """
    order.override_delivery_method = None
    order.delivery_method_set_at = teraz
    order.delivery_method_set_by = user_id
    order.bl_delivery_method_pending = False
    if order.bl_status_pending_id in sposoby.STATUS_PO_SPAKOWANIU.values():
        order.bl_status_pending_id = None
    # Przepakowanie na kuriera bez kuriera nie ma sensu (jak przy zmianie na transport).
    _zdejmij_baner_przepakowania_na_kuriera(order)
    zapisz_log(order, 'sposob_dostawy', stary, None, user_id=user_id, teraz=teraz)
    podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)
    return {'zmieniono': True, 'przepakowanie': False}


# Limity pól adresu w Base. (setOrderFields): dłuższej wartości Base. nie przyjmie.
LIMIT_ADRESU, LIMIT_KODU, LIMIT_MIASTA = 156, 20, 100
# (M7) Tylko cyfry ASCII: `\d` i str.isdigit() przepuszczają też cyfry Unicode (np. „٣٥-٣١٠”),
# które poszłyby do Base. i wypadły z filtra województw.
_KOD_PL = re.compile(r'[0-9]{2}-[0-9]{3}')


def zmien_adres(order, adres, kod, miasto, user_id=None, teraz=None):
    """
    Poprawka adresu dostawy z zakładki Logistyka. Zapisuje w CRM i stawia znacznik
    `bl_address_pending` — do Base. wysyła go dopychacz w tle (bl_sync), nigdy
    żądanie HTTP. Zwraca True, gdy adres się zmienił. NIE commituje.

    Geokoder sam zauważy nowy adres (inny skrót `address_hash`): punkt automatu
    policzy od nowa, a przy punkcie ręcznym tylko zapali „adres zmieniony”.

    Przegląd W1: tylko zamówienia, które jeszcze jadą — nie wydane, nie anulowane,
    nie zamknięte i bez utworzonej przesyłki (etykieta kuriera miałaby stary adres).
    """
    def czysty(wartosc):
        return ' '.join(str(wartosc).split()) if isinstance(wartosc, str) else None

    adres, kod, miasto = czysty(adres), czysty(kod), czysty(miasto)
    if adres is None or kod is None or miasto is None:
        raise LogistykaBlad(u'Podaj adres, kod pocztowy i miejscowość jako tekst.', status=422)
    if not adres or not miasto:
        raise LogistykaBlad(u'Adres (ulica i numer) i miejscowość są wymagane.', status=422)
    if len(adres) > LIMIT_ADRESU or len(kod) > LIMIT_KODU or len(miasto) > LIMIT_MIASTA:
        raise LogistykaBlad(u'Za długi adres: ulica do {} znaków, kod do {}, miejscowość do {}.'.format(
            LIMIT_ADRESU, LIMIT_KODU, LIMIT_MIASTA), status=422)
    if kod and ((order.delivery_country_code or '').strip().upper() or 'PL') == 'PL':
        if kod.isascii() and kod.isdigit() and len(kod) == 5:
            kod = kod[:2] + '-' + kod[2:]
        elif not _KOD_PL.fullmatch(kod):
            raise LogistykaBlad(u'Kod pocztowy w formacie 00-000.', status=422)

    numer = order.internal_order_number
    if order.handed_over_at is not None:
        raise LogistykaBlad(u'Zamówienie {} zostało już wydane klientowi.'.format(numer))
    if not aktywne_produkty(order):
        raise LogistykaBlad(u'Zamówienie {} jest anulowane.'.format(numer))
    if order.logistics_closed_at is not None:
        raise LogistykaBlad(u'Zamówienie {} jest zamknięte w logistyce.'.format(numer))
    if order.shipping_package_id or order.shipping_tracking_number:
        raise LogistykaBlad(u'Zamówienie {} ma już utworzoną przesyłkę — adres zmień u kuriera '
                            u'i w Base.'.format(numer))

    # Przegląd D4: dane z Base. bywają z podwójną spacją — porównujemy po tym samym
    # czyszczeniu, inaczej zapis okna bez zmian liczyłby się jako poprawka.
    stary = tuple(czysty(x or '') for x in (order.delivery_address, order.delivery_postcode,
                                            order.delivery_city))
    if stary == (adres, kod, miasto):
        return False
    # Etap 3: na trasie zatwierdzonej adres zmieniamy dopiero po cofnięciu zatwierdzenia.
    # PO porównaniu bez zmian (R5) — zapis okna bez zmian ma zostać no-opem (False),
    # nie 409, nawet gdy zamówienie leży na zatwierdzonej trasie.
    _przystanek_do_zmiany(order, True, u'popraw adres')
    teraz = teraz or get_local_now()
    order.delivery_address, order.delivery_postcode, order.delivery_city = adres, kod or None, miasto
    order.bl_address_pending = True
    notatka = u'Było: {}; jest: {}'.format(u', '.join(x for x in stary if x) or u'brak',
                                          u', '.join(x for x in (adres, kod, miasto) if x))
    zapisz_log(order, 'adres', u'{} {}'.format(stary[1], stary[2]).strip()[:64] or None,
               u'{} {}'.format(kod, miasto).strip()[:64], user_id=user_id,
               note=notatka[:255], teraz=teraz)
    # Tablet pokazuje miasto i kod pozycji — ETag kolejek liczy się z updated_at pozycji.
    podbij_pozycje(order, teraz)
    return True


def wydaj_klientowi(order, user_id=None, teraz=None):
    if sposoby.normalizuj(order.override_delivery_method) != sposoby.ODBIOR:
        raise LogistykaBlad(u'„Wydane klientowi” dotyczy tylko odbioru osobistego.')
    if order.handed_over_at is not None:
        raise LogistykaBlad(u'Zamówienie {} jest już wydane.'.format(order.internal_order_number))
    # Spec 4.2 i 4.4: wydanie nie czeka na weryfikację — działa ze 'spakowane' i 'zweryfikowane'.
    if not wszystkie_w(order, ('spakowane', 'zweryfikowane')):
        raise LogistykaBlad(u'Zamówienie {} nie jest jeszcze w całości spakowane.'.format(
            order.internal_order_number))
    teraz = teraz or get_local_now()
    order.handed_over_at = teraz
    order.handed_over_by = user_id
    order.bl_status_pending_id = sposoby.STATUS_ODEBRANE
    for p in aktywne_produkty(order):
        p.current_status = 'dostarczone'
    zapisz_log(order, 'wydane', user_id=user_id, teraz=teraz)
    podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)


def przenies_osierocone_z_logistyki(teraz=None):
    """
    Produkty w `czeka_na_logistyke` → `czeka_na_pakowanie`. Zwraca liczbę przeniesionych.

    Migracja etapu 1 przenosi je raz, ale deploy.sh robi migrate → przeliczenie klientów
    (do 300 s) → restart, a przez ten czas STARY kod wciąż zapisuje `czeka_na_logistyke`.
    Po restarcie taki produkt nie ma kolejki na tablecie ani filtra na liście — wisi
    niewidoczny. Cron zamiata go tą samą drogą, jaką idzie dziś wyjście z produkcji
    (complete_task). Idempotentne: gdy nic nie zostało, zwraca 0.
    """
    from modules.production.models import ProductionProduct
    teraz = teraz or get_local_now()
    produkty = (ProductionProduct.query
                .filter(ProductionProduct.current_status == 'czeka_na_logistyke').all())
    zamowienia = {}
    for p in produkty:
        p.current_status = 'czeka_na_pakowanie'
        p.updated_at = teraz  # ETag kolejki pakowania na tablecie
        if p.order is not None:
            zamowienia[p.order.id] = p.order
    for order in zamowienia.values():
        odnotuj_wejscie_do_pakowania(order, teraz)
        przelicz_zamkniecie(order, teraz)
    return len(produkty)


# Znacznik w prod_config: przestawienie wydanych zamówień na 'dostarczone' (dostarcz_wydane) już się odbyło.
KLUCZ_WYDANE_DOSTARCZONE = 'logistyka_wydane_dostarczone'


def _znacznik_wydane_dostarczone():
    """Wiersz prod_config ze znacznikiem dostarcz_wydane albo None, gdy przestawienie jeszcze się nie odbyło."""
    from modules.production.models import ProductionConfig
    return ProductionConfig.query.filter_by(config_key=KLUCZ_WYDANE_DOSTARCZONE).first()


def dostarcz_wydane(teraz=None):
    """
    Pozycje 'spakowane' zamówień już wydanych klientowi (handed_over_at) → 'dostarczone'.
    Zwraca liczbę przestawionych pozycji. JEDNORAZOWE: po pierwszym udanym przebiegu w prod_config
    zostaje znacznik `logistyka_wydane_dostarczone` (chwila przebiegu, '%Y-%m-%d %H:%M:%S', te same
    pola co `weryfikacja.data_wdrozenia()`), a każdy kolejny przebieg widzi go i zwraca 0, nie pytając
    o pozycje.

    Od kroku 4.3 „Wydane klientowi” ustawia 'dostarczone' samo (delivery.wydaj), ale zamówienia
    wydane wcześniej zostały ze 'spakowane'. Migracja tego NIE robi: deploy.sh wykonuje ją PRZED
    restartem, a stary kod w oknie wdrożenia ma Enum bez 'dostarczone' — pierwszy odczyt takiego
    wiersza rzuciłby LookupError (500 na listach). Dlatego przepisanie idzie z crona po restarcie,
    przez ORM (audyt prod_product_events działa tylko tam) i z podbiciem updated_at (ETag kolejek
    tabletów). Obejmuje zamówienia wydane przed wdrożeniem, także te wydane przez stary kod w oknie
    między migracją a restartem.

    DLACZEGO TYLKO RAZ: cron chodzi co godzinę bez ograniczeń. Zamówienie wydane klientowi, w którym
    pozycja przeszła doróbkę albo Base. dołożył nową, po ponownym spakowaniu jest znów 'spakowane'
    przy niezmienionym handed_over_at. Przebieg „zawsze” przestawiłby ją po godzinie na 'dostarczone',
    choć klient jej nie odebrał. Po znaczniku taka pozycja zostaje 'spakowane'.

    Znacznik powstaje także wtedy, gdy nie było nic do przestawienia, i w tej samej transakcji co
    przestawienie (commituje wołający): nieudany przebieg cofa jedno i drugie, więc następny powtórzy
    całość. Dwa równoległe przebiegi: `config_key` ma unikalność (model `ProductionConfig`), więc
    znacznik wstawiamy PRZED przestawieniem, w SAVEPOINT. Drugi przebieg czeka na pierwszy (klucz
    unikalny), po jego commicie dostaje duplikat, łapie go i zwraca 0 bez błędu — pozycji nie rusza.
    """
    from modules.production.models import ProductionConfig, ProductionOrder, ProductionProduct
    teraz = teraz or get_local_now()
    if _znacznik_wydane_dostarczone() is not None:
        return 0
    try:
        with db.session.begin_nested():
            db.session.add(ProductionConfig(
                config_key=KLUCZ_WYDANE_DOSTARCZONE,
                config_value=teraz.strftime('%Y-%m-%d %H:%M:%S'),
                config_type='string',
                config_description=u'Logistyka: wydane zamówienia przestawione na dostarczone (krok 4.3, jednorazowo)'))
            db.session.flush()
    except IntegrityError:
        # Równoległy przebieg zdążył ze znacznikiem (i z przestawieniem) — nic do roboty.
        return 0
    produkty = (ProductionProduct.query
                .join(ProductionOrder, ProductionOrder.id == ProductionProduct.order_id)
                .filter(ProductionOrder.handed_over_at.isnot(None),
                        ProductionProduct.current_status == 'spakowane')
                .all())
    for p in produkty:
        p.current_status = 'dostarczone'
        p.updated_at = teraz
    return len(produkty)


def przelicz_otwarte(teraz=None):
    """
    Siatka bezpieczeństwa dla crona: przelicza zamówienia otwarte oraz zamknięte,
    które znów mają aktywne produkty (Base. dołożył pozycję, doróbka) albo (M10) mają
    transport własny i przystanek na trasie AKTYWNEJ (roboczej/zatwierdzonej) — takie
    zamówienie jeszcze nie pojechało, więc zamknięte być nie może (np. trasa przywrócona
    albo zamówienie dodane do trasy tuż przed odhaczeniem innej), a samo nie wróci:
    spakowane lub dalej (w całości) nie łapie się na warunek „znów aktywne pozycje”.
    Każde przeliczane zamówienie przechodzi też przez regułę unieważniania etapów
    (weryfikacja.uniewaznij_etapy) — zweryfikowane w całości zostaje zamknięte i nietknięte.
    """
    from modules.production.models import ProductionOrder, ProductionProduct
    teraz = teraz or get_local_now()
    otwarte = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
               .filter(ProductionOrder.logistics_closed_at.is_(None)).all())
    na_aktywnych_trasach = (db.session.query(RouteStop.order_id)
                            .join(Route, Route.id == RouteStop.route_id)
                            .filter(Route.status.in_(STATUSY_TRASY_AKTYWNE)))
    do_otwarcia = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                   .filter(ProductionOrder.logistics_closed_at.isnot(None))
                   .filter(or_(
                       ProductionOrder.products.any(ProductionProduct.current_status.notin_(
                           sposoby.STATUSY_PO_SPAKOWANIU + ('anulowane',))),
                       and_(ProductionOrder.override_delivery_method == sposoby.TRANSPORT,
                            ProductionOrder.id.in_(na_aktywnych_trasach))))
                   .all())
    # Siatka bezpieczeństwa jednej reguły (spec 8.5): ścieżki, które nie wołają jej same (np. przyszłe
    # zmiany statusu), dostają ją najpóźniej przy godzinnym przebiegu. Bez pracy nie pyta bazy.
    from modules.production.logistics.services import weryfikacja
    zmienione = 0
    for order in otwarte + do_otwarcia:
        weryfikacja.uniewaznij_etapy(order, teraz, u'kontrola cykliczna')
        if przelicz_zamkniecie(order, teraz):
            zmienione += 1
    return zmienione
