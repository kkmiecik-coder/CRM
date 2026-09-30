# -*- coding: utf-8 -*-
"""
Weryfikacja paczek (logistyka etap 4, krok 4.3, spec 4.4–4.5 i 8).

Tu żyje jedna reguła unieważniania etapów (paczki, weryfikacja, załadunek) po powrocie pozycji do
produkcji, definicja listy „Do weryfikacji” i akcje stanowiska Weryfikacja. Funkcje NIE commitują —
robi to wołający (API mobilne przez @with_idempotency, panel, cron, synchronizacja).
"""
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import selectinload

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import sposoby
from modules.production.logistics.models import STATUSY_TRASY_AKTYWNE
from modules.production.logistics.services import delivery, paczki, routes
from modules.production.models import ProductionConfig, ProductionOrder, ProductionProduct, get_local_now
from modules.production.services.station_catalog import STATION_LABELS, STATION_PENDING_STATUS

logger = get_structured_logger('production.logistics.weryfikacja')

# Pozycje, które wracają do 'spakowane', gdy zamówienie wróci do produkcji. 'dostarczone' zostaje
# (decyzja Konrada 30.09): towar u klienta jest u klienta.
_COFANE_DO_SPAKOWANYCH = tuple(st for st in sposoby.STATUSY_LOGISTYCZNE if st != 'dostarczone')

STANOWISKO = 'verification'
# Zamówienia zamknięte w Logistyce (kurier) są na liście przez tyle dni od spakowania (decyzja 30.09).
DNI_LISTY = 7
# Chwila wdrożenia kroku 4.3 — wiersz prod_config z migracji 2026-09-30-logistyka-weryfikacja.sql.
KLUCZ_OD = 'logistyka_weryfikacja_od'
POWODY_PROBLEMU = {
    'brak_elementu': u'Brak elementu',
    'uszkodzenie': u'Uszkodzenie',
    'etykieta': u'Etykieta',
    'opakowanie': u'Opakowanie',
    'inne': u'Inne',
}
# Napis etapu zamówienia po spakowaniu (telefon i panel Logistyki, spec 4.1 i 11).
NAZWY_ETAPOW = {
    'spakowane': u'Spakowane — czeka na weryfikację',
    'zweryfikowane': u'Zweryfikowane',
    'zaladowane': u'Załadowane',
    'dostarczone': u'Dostarczone',
}
# Etap przed spakowaniem = stanowisko, na którym pozycja czeka (jak kolumna listy Logistyki).
_NAZWA_STANOWISKA = {status: STATION_LABELS[kod] for kod, status in STATION_PENDING_STATUS.items()}
# Nieczytelne wartości KLUCZ_OD, o których już ostrzegliśmy w tym procesie (data_wdrozenia()).
_OSTRZEZONE_WARTOSCI = set()


def data_wdrozenia():
    """Chwila wdrożenia kroku 4.3 (prod_config) albo None — wtedy zakres listy to samo okno dni."""
    wiersz = ProductionConfig.query.filter_by(config_key=KLUCZ_OD).first()
    tekst = (wiersz.config_value or '').strip() if wiersz is not None else ''
    if not tekst:
        return None
    try:
        return datetime.strptime(tekst[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        # Telefon odpytuje listę co kilkanaście sekund — ostrzegamy raz na wartość w procesie.
        if tekst not in _OSTRZEZONE_WARTOSCI:
            _OSTRZEZONE_WARTOSCI.add(tekst)
            logger.warning(u"Nieczytelna data w prod_config '{}': {!r} - lista Do weryfikacji liczy "
                           u"samo okno {} dni".format(KLUCZ_OD, tekst, DNI_LISTY))
        return None


def poczatek_okna(teraz):
    """Od kiedy zamówienia zamknięte w Logistyce trafiają na listę: ostatnie DNI_LISTY dni, ale nie
    wcześniej niż wdrożenie kroku 4.3 (inaczej w dniu wdrożenia lista miałaby ~110 starych zamówień)."""
    okno = teraz - timedelta(days=DNI_LISTY)
    wdrozenie = data_wdrozenia()
    return max(okno, wdrozenie) if wdrozenie is not None else okno


def _wszystkie_sql(statusy):
    """SQL: zamówienie ma pozycję w `statusy`, a żadna niezanulowana nie jest spoza `statusy`."""
    statusy = tuple(statusy)
    return and_(
        ProductionOrder.products.any(ProductionProduct.current_status.in_(statusy)),
        ~ProductionOrder.products.any(ProductionProduct.current_status.notin_(statusy + ('anulowane',))))


def warunek_zakresu(teraz):
    """Zamówienie otwarte w Logistyce albo z pozycją spakowaną od poczatek_okna(teraz)."""
    return or_(ProductionOrder.logistics_closed_at.is_(None),
               ProductionOrder.products.any(and_(
                   ProductionProduct.current_status != 'anulowane',
                   ProductionProduct.packaging_completed_at >= poczatek_okna(teraz))))


def warunek_do_weryfikacji(teraz):
    """„Do weryfikacji” (spec 8.2): wszystkie niezanulowane pozycje 'spakowane', w zakresie listy.
    Licznik dashboardu i filtr panelu Logistyki."""
    return and_(_wszystkie_sql(('spakowane',)), warunek_zakresu(teraz))


def warunek_problemu():
    return ProductionOrder.problem_at.isnot(None)


def warunek_bez_paczek(teraz):
    """Do weryfikacji, ale bez aktualnej deklaracji paczek (stara appka, zmiana admina)."""
    return and_(warunek_do_weryfikacji(teraz), ProductionOrder.packages_declared_at.is_(None))


def warunek_listy(teraz):
    """Lista telefonu: do weryfikacji i zweryfikowane (w tym samym zakresie — skaner rozpoznaje paczki
    lokalnie, więc zweryfikowane muszą zostać w telefonie) plus zawsze zamówienia z problemem."""
    return or_(warunek_problemu(),
               and_(_wszystkie_sql(('spakowane', 'zweryfikowane')), warunek_zakresu(teraz)))


def liczba_do_weryfikacji(teraz):
    return db.session.query(func.count(ProductionOrder.id)).filter(
        warunek_do_weryfikacji(teraz)).scalar() or 0


def liczba_problemow():
    return db.session.query(func.count(ProductionOrder.id)).filter(warunek_problemu()).scalar() or 0


def nazwa_etapu(produkt):
    return (NAZWY_ETAPOW.get(produkt.current_status) or _NAZWA_STANOWISKA.get(produkt.current_status)
            or produkt.status_display_name)


def etap(aktywne):
    """(status, napis) najbardziej zaległej aktywnej pozycji; bez aktywnych — anulowane."""
    if not aktywne:
        return 'anulowane', u'Anulowane'
    kolejnosc = sposoby.STATUSY_PO_SPAKOWANIU
    najwczesniejsza = min(aktywne, key=lambda p: kolejnosc.index(p.current_status)
                          if p.current_status in kolejnosc else -1)
    return najwczesniejsza.current_status, nazwa_etapu(najwczesniejsza)


def _iso(chwila):
    return chwila.isoformat() if chwila else None


def _spakowano(order):
    daty = [p.packaging_completed_at for p in delivery.aktywne_produkty(order) if p.packaging_completed_at]
    return max(daty) if daty else None


def _trasa_aktywna(order, trasa):
    if trasa is None or trasa.status not in STATUSY_TRASY_AKTYWNE:
        return None
    return trasa if sposoby.normalizuj(order.override_delivery_method) == sposoby.TRANSPORT else None


def serializuj_problem(order):
    if order.problem_at is None:
        return None
    return {'reason': order.problem_reason,
            'reason_label': POWODY_PROBLEMU.get(order.problem_reason, order.problem_reason),
            'note': order.problem_note, 'at': _iso(order.problem_at),
            'by_worker_id': order.problem_by_worker_id}


def serializuj_zamowienie(order, paczki_zamowienia, trasa=None, z_pozycjami=False):
    """Zamówienie w API telefonu (kontrakt w planie kroku 4.3). `trasa` — dowolnego statusu (z
    routes.trasy_zamowien); na telefon trafia tylko aktywna trasa transportu własnego."""
    aktywne = delivery.aktywne_produkty(order)
    status, napis = etap(aktywne)
    dane = {
        'order_id': order.id,
        'internal_order_number': order.internal_order_number,
        'baselinker_order_id': order.baselinker_order_id,
        'client_name': order.client_name,
        'delivery_city': order.delivery_city,
        'stage': status,
        'stage_label': napis,
        'packed_at': _iso(_spakowano(order)),
        'verified_at': _iso(order.verified_at),
        'transport': sposoby.transport_payload(order, _trasa_aktywna(order, trasa)),
        'packages': [paczki.serializuj_paczke(p) for p in paczki_zamowienia],
        'packages_total': len(paczki_zamowienia),
        'packages_verified': sum(1 for p in paczki_zamowienia if p.verified_at is not None),
        'no_packages': not paczki_zamowienia and delivery.wszystkie_w(order, ('spakowane', 'zweryfikowane')),
        'problem': serializuj_problem(order),
    }
    if z_pozycjami:
        dane['items'] = [{
            'id': p.id, 'short_id': p.short_product_id, 'product_name': p.original_product_name,
            'quantity': p.quantity, 'status': p.current_status, 'status_label': nazwa_etapu(p),
            'volume_m3': float(p.volume_m3) if p.volume_m3 is not None else None,
        } for p in sorted(order.products, key=lambda x: (x.product_sequence_in_order or 0, x.id or 0))]
    return dane


def lista(teraz):
    """
    Zamówienia listy telefonu w kolejności specu 8.2 (aktywna trasa transportu z najbliższą datą
    początku, potem spakowanie rosnąco, potem numer) + mapy paczek i tras — po jednym zapytaniu na
    mapę, bez zapytań na wiersz.
    """
    zamowienia = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                  .filter(warunek_listy(teraz)).all())
    ids = [o.id for o in zamowienia]
    pakunki = paczki.aktualne_paczki_zamowien(ids)
    trasy = routes.trasy_zamowien(ids)

    def klucz(order):
        aktywna = _trasa_aktywna(order, trasy.get(order.id))
        spakowano = _spakowano(order)
        return (aktywna is None, aktywna.date_from if aktywna is not None else date.max,
                spakowano or datetime.max, order.internal_order_number or '')

    zamowienia.sort(key=klucz)
    return zamowienia, pakunki, trasy


def podpis_listy(zamowienia, pakunki, teraz):
    """Części ETagu listy: dzień (okno dni przesuwa się bez zmian danych), liczba zamówień, najnowszy
    updated_at zamówień (problem, weryfikacja, dane klienta z synchronizacji — zmiany samych kolumn
    zamówienia), najnowszy updated_at i liczba pozycji (akcje Weryfikacji, deklaracje i zmiany tras
    podbijają pozycje), stan paczek (weryfikacja, wydruki)."""
    pozycje = [p for o in zamowienia for p in o.products]
    znaczniki = [p.updated_at for p in pozycje if p.updated_at]
    znaczniki_zamowien = [o.updated_at for o in zamowienia if o.updated_at]
    wszystkie_paczki = [p for lista_paczek in pakunki.values() for p in lista_paczek]
    return (teraz.date().isoformat(), len(zamowienia),
            int(max(znaczniki_zamowien).timestamp()) if znaczniki_zamowien else 0,
            int(max(znaczniki).timestamp()) if znaczniki else 0, len(pozycje), len(wszystkie_paczki),
            sum(1 for p in wszystkie_paczki if p.verified_at is not None),
            sum(p.label_print_count or 0 for p in wszystkie_paczki))


def _jest_praca_dla_reguly(order, aktywne):
    """
    Czy reguła uniewaznij_etapy ma co robić NA STANIE, KTÓRY WIDZI W PAMIĘCI: któraś niezanulowana pozycja
    nie jest „spakowane lub dalej”, a zamówienie ma jeszcze deklarację paczek, weryfikację albo pozycje do
    cofnięcia z etapów logistycznych. Czyta tylko kolumny zamówienia i statusy już wczytanych pozycji.
    """
    if not aktywne or all(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne):
        return False
    cofane = [p for p in aktywne if p.current_status in _COFANE_DO_SPAKOWANYCH]
    return bool(cofane) or order.packages_declared_at is not None or order.verified_at is not None


def uniewaznij_etapy(order, teraz, powod, user_id=None, worker_id=None, device_id=None):
    """
    Jedna reguła (spec 4.5, ostatni wiersz, i 8.5): zamówienie, którego któraś niezanulowana pozycja
    nie jest „spakowane lub dalej” (doróbka, nowa pozycja z Base., przepakowanie, cofnięcie do
    pakowania, ręczna zmiana statusu), traci paczki (unieważnione razem z oczekującymi zadaniami
    druku), weryfikację i załadunek, a jego pozycje zweryfikowane i załadowane wracają do
    'spakowane'. Po ponownym spakowaniu zamówienie przechodzi kroki od nowa.

    `powod` — tekst do logu i komunikatu wygaszonego zadania druku (np. u'nowa pozycja z Base.').
    Zwraca True, gdy coś zmieniła. NIE commituje.

    REGUŁA SAMA ROBI ODCZYT BIEŻĄCY (nie wymaga go od wołającego). Wołający (cron, panel, synchronizacja)
    podają zamówienie i pozycje z migawki MySQL (REPEATABLE READ), a decyzja „co cofnąć” na takim stanie
    potrafiła unieważnić świeżą deklarację paczek innego urządzenia albo zalogować drugie
    `weryfikacja_cofnieta` po już zatwierdzonym „Cofnij weryfikację”. Dlatego:
    1. Tania wstępna ocena na stanie wołającego (`_jest_praca_dla_reguly`, bez zapytań): brak pracy →
       False bez dotykania bazy. Woła ją cron dla każdego otwartego zamówienia.
    2. Widoczna praca → potwierdzenie na odczycie bieżącym, w kolejności Weryfikacji: zamówienie FOR
       UPDATE po PK z `populate_existing` → paczki FOR UPDATE → pozycje po PK FOR UPDATE z
       `populate_existing` (`paczki.zablokuj_stan`). Wołający, którzy już trzymają te blokady
       (`cofnij_do_pakowania`, hurtowa zmiana statusu po zablokowaniu zamówień i pozycji), dostają je
       bez czekania.
    3. Dopiero na tym stanie liczy, co cofnąć, i działa. Gdy po odczycie bieżącym pracy nie ma, nie robi
       nic i niczego nie loguje.

    Niezapisane zmiany wołającego nie giną: `populate_existing` NADPISUJE atrybuty obiektów w sesji, więc
    przed pierwszym zapytaniem jest jawny `flush()` (także gdy wołający wyłączył autoflush) — zmiany
    lądują w bazie, a odczyt wczytuje z niej te same wartości. Zapis zamówienia poprzedza zapis pozycji
    w jednym flushu (kolejność zależności tabel), więc flush nie odwraca kolejności blokad.
    """
    if not _jest_praca_dla_reguly(order, delivery.aktywne_produkty(order)):
        return False
    db.session.flush()   # niezapisane zmiany wołającego do bazy PRZED odczytem nadpisującym obiekty
    istnieje = (ProductionOrder.query.filter(ProductionOrder.id == order.id)
                .with_for_update().populate_existing().first())
    if istnieje is None:
        return False
    stare = paczki.zablokuj_stan(order)
    aktywne = delivery.aktywne_produkty(order)
    if not _jest_praca_dla_reguly(order, aktywne):
        return False
    cofane = [p for p in aktywne if p.current_status in _COFANE_DO_SPAKOWANYCH]
    notatka = (powod or u'')[:255] or None
    for p in cofane:
        p.current_status = 'spakowane'
    if order.verified_at is not None:
        order.verified_at = None
        order.verified_by_worker_id = None
        delivery.zapisz_log(order, 'weryfikacja_cofnieta', note=notatka, user_id=user_id,
                            worker_id=worker_id, device_id=device_id, teraz=teraz)
    if order.packages_declared_at is not None:
        order.packages_declared_at = None
        paczki.uniewaznij(stare, teraz, powod=notatka or u'unieważnienie etapów')
        delivery.zapisz_log(order, 'paczki', paczki.opis_paczek(stare), None, note=notatka,
                            user_id=user_id, worker_id=worker_id, device_id=device_id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return True


METODY = ('skan', 'reczne')   # = ProductionPackage.SPOSOBY_POTWIERDZENIA
_OPIS_METODY = {'skan': u'skan', 'reczne': u'ręcznie'}


class WeryfikacjaBlad(Exception):
    """Odmowa z kodem dla appki (`error`) i komunikatem dla człowieka (`message`)."""

    def __init__(self, kod, komunikat, status=409):
        super().__init__(komunikat)
        self.kod = kod
        self.komunikat = komunikat
        self.status = status


def sprawdz_stan(order):
    """
    Zamówienie, na którym Weryfikacja może działać: każda niezanulowana pozycja 'spakowane' albo
    'zweryfikowane' (spec 8.3). Załadowane i dostarczone → 409 order_status (spec 4.5: cofnięcia
    Weryfikacji działają do załadunku). Zwraca aktywne pozycje.
    """
    numer = order.internal_order_number
    aktywne = delivery.aktywne_produkty(order)
    if not aktywne:
        raise WeryfikacjaBlad('order_status', u'Zamówienie {} jest anulowane.'.format(numer))
    if any(p.current_status not in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne):
        raise WeryfikacjaBlad('order_not_packed', u'Zamówienie {} nie jest jeszcze w całości spakowane — '
                              u'weryfikacja po spakowaniu wszystkich pozycji.'.format(numer))
    if any(p.current_status == 'dostarczone' for p in aktywne):
        raise WeryfikacjaBlad('order_status', u'Zamówienie {} jest już dostarczone.'.format(numer))
    if any(p.current_status == 'zaladowane' for p in aktywne):
        raise WeryfikacjaBlad('order_status', u'Zamówienie {} jest już załadowane.'.format(numer))
    return aktywne


def zablokuj_stan(order):
    """
    Odczyt bieżący stanu, na którym zapis Weryfikacji ma zdecydować. Zwraca aktualne paczki zamówienia.
    Definicja odczytu (kolejność blokad, dlaczego bieżący, a nie migawka) siedzi w `paczki.zablokuj_stan`,
    bo woła ją też deklaracja paczek: zamówienie FOR UPDATE trzyma już router → paczki FOR UPDATE →
    pozycje po PK FOR UPDATE → dopiero zapisy.
    """
    return paczki.zablokuj_stan(order)


def stan_do_zapisu(order):
    """
    `(aktywne pozycje, aktualne paczki)` z odczytu bieżącego (zablokuj_stan) — dopiero na nim sprawdzenia
    sprawdz_stan (409 order_status / order_not_packed). Wołać w każdym zapisie Weryfikacji, zanim cokolwiek
    zostanie zapisane.
    """
    aktualne = zablokuj_stan(order)
    return sprawdz_stan(order), aktualne


def problem_otwarty(order):
    return WeryfikacjaBlad('problem_open', u'Zamówienie {} ma zgłoszony problem ({}) — najpierw go '
                           u'rozwiąż.'.format(order.internal_order_number,
                                              POWODY_PROBLEMU.get(order.problem_reason, order.problem_reason)))


def sprawdz_zakres(order, teraz):
    """
    Zapis Weryfikacji tylko na zamówieniu z zakresu listy (fala końcowa kroku 4.3). Wołana w KAŻDYM
    zapisie poza `rozwiaz_problem`, PO blokadach i PO sprawdzeniach stanu (`stan_do_zapisu`,
    `problem_open`, `no_packages`, `order_not_verified` — bardziej konkretny kod wygrywa), tuż przed
    pierwszym zapisem. Bez niej „Cofnij do pakowania” na zamówieniu kurierskim sprzed miesięcy
    wysłałoby do Base. status 138620, otworzyło je w Logistyce i dało tabletom pakowania.

    Zakres = `warunek_zakresu(teraz)` (zamówienie otwarte w Logistyce albo z pozycją spakowaną od
    `poczatek_okna(teraz)`) ALBO otwarty problem (`order.problem_at`, z obiektu już zablokowanego i
    odświeżonego odczytem bieżącym). Zamówienie z otwartym problemem zostaje w zakresie bez względu na
    wiek, bo problem trzeba móc rozwiązać i cofnąć do pakowania. Poza zakresem: 409 `order_status`,
    więc bez zapamiętania w idempotencji (BLEDY_DO_PONOWIENIA) i bez startu dopychacza Base.
    (`zaplanuj_po_commicie` rusza dopiero po tej kontroli).

    Zwykły SELECT, nie FOR UPDATE: podzapytanie po pozycjach blokowałoby luki indeksów. Migawka MySQL
    (REPEATABLE READ) sprzed czekania na blokady tu nie szkodzi: to tylko obrona zakresu, a błąd nie jest
    zapamiętany, więc telefon może ponowić ze świeżą migawką. Świeżo spakowane zamówienie nie wypadnie
    z zakresu przez starą migawkę: sprzed spakowania widać je jako otwarte w Logistyce, a po spakowaniu
    ma packaging_completed_at z ostatnich chwil, czyli w oknie listy.
    """
    if order.problem_at is not None:
        return
    w_zakresie = (db.session.query(ProductionOrder.id)
                  .filter(ProductionOrder.id == order.id, warunek_zakresu(teraz)).first())
    if w_zakresie is None:
        raise WeryfikacjaBlad('order_status', u'Zamówienie {} jest poza listą Weryfikacji (spakowane ponad {} '
                              u'dni temu albo przed uruchomieniem Weryfikacji).'.format(
                                  order.internal_order_number, DNI_LISTY))


def _oznacz(paczka, metoda, worker_id, teraz):
    paczka.verified_at = teraz
    paczka.verified_by_worker_id = worker_id
    paczka.verified_method = metoda


def _zweryfikuj_zamowienie(order, aktywne, aktualne, metoda, worker_id, device_id, teraz):
    """Wszystkie ważne paczki sprawdzone → pozycje 'zweryfikowane', kto i kiedy, log (spec 8.3)."""
    for p in aktywne:
        p.current_status = 'zweryfikowane'
    order.verified_at = teraz
    order.verified_by_worker_id = worker_id
    delivery.zapisz_log(order, 'weryfikacja', None, paczki.opis_paczek(aktualne), worker_id=worker_id,
                        device_id=device_id, note=_OPIS_METODY[metoda], teraz=teraz)
    delivery.przelicz_zamkniecie(order, teraz)


def zweryfikuj_paczke(paczka, order, metoda, worker_id=None, device_id=None, teraz=None):
    """
    Skan albo ręczne odhaczenie jednej paczki (spec 8.3). Zwraca (zmieniono, zamówienie_zweryfikowane).
    Ostatnia ważna paczka → zamówienie 'zweryfikowane'. Ponowny skan sprawdzonej paczki = OK bez zmian,
    chyba że WSZYSTKIE aktualne paczki są już sprawdzone, a pozycje jeszcze nie są 'zweryfikowane'
    (po hurtowej zmianie statusów) — wtedy ten skan domyka zamówienie i zwraca (True, True).
    Zapis tylko w zakresie listy (sprawdz_zakres).
    Router bierze paczki.zablokuj_deklaracje(), potem zamówienie i paczkę FOR UPDATE (w tej kolejności —
    jak deklaracja, zamówienie → paczki). Stan pozycji i paczek, na którym funkcja decyduje, pochodzi
    z odczytu bieżącego (stan_do_zapisu) — także „czy to była ostatnia paczka”. NIE commituje.
    """
    teraz = teraz or get_local_now()
    if paczka.voided_at is not None:
        raise WeryfikacjaBlad('package_void', u'Etykieta nieaktualna — paczki zadeklarowano ponownie.')
    aktywne, aktualne = stan_do_zapisu(order)
    if order.problem_at is not None:
        raise problem_otwarty(order)
    sprawdz_zakres(order, teraz)
    if paczka.verified_at is not None:
        zweryfikowane = all(p.current_status == 'zweryfikowane' for p in aktywne)
        if not zweryfikowane and all(p.verified_at is not None for p in aktualne):
            # Wszystkie aktualne paczki są już sprawdzone, a pozycje nie są zweryfikowane — tak zostaje
            # po hurtowej zmianie „zweryfikowane” → „spakowane” (paczki zachowują znaczniki). Żaden
            # skan nie zmieniłby wtedy niczego, więc ponowny skan domyka zamówienie.
            _zweryfikuj_zamowienie(order, aktywne, aktualne, metoda, worker_id, device_id, teraz)
            delivery.podbij_pozycje(order, teraz)
            return True, True
        return False, zweryfikowane
    _oznacz(paczka, metoda, worker_id, teraz)
    zweryfikowane = all(p.verified_at is not None for p in aktualne)
    if zweryfikowane:
        _zweryfikuj_zamowienie(order, aktywne, aktualne, metoda, worker_id, device_id, teraz)
    delivery.podbij_pozycje(order, teraz)
    return True, zweryfikowane


def zweryfikuj_wszystkie(order, worker_id=None, device_id=None, teraz=None):
    """„Zweryfikuj wszystkie” (spec 8.3): niesprawdzone ważne paczki ręcznie. Zwraca True, gdy coś
    zmieniła. Weryfikacja wymaga zadeklarowanych paczek (spec 4.4) → bez nich 409 no_packages."""
    teraz = teraz or get_local_now()
    aktywne, aktualne = stan_do_zapisu(order)
    if order.problem_at is not None:
        raise problem_otwarty(order)
    if not aktualne:
        raise WeryfikacjaBlad('no_packages', u'Zamówienie {} nie ma zadeklarowanych paczek — najpierw '
                              u'zadeklaruj paczki.'.format(order.internal_order_number))
    sprawdz_zakres(order, teraz)
    niesprawdzone = [p for p in aktualne if p.verified_at is None]
    if not niesprawdzone and all(p.current_status == 'zweryfikowane' for p in aktywne):
        return False
    for p in niesprawdzone:
        _oznacz(p, 'reczne', worker_id, teraz)
    _zweryfikuj_zamowienie(order, aktywne, aktualne, 'reczne', worker_id, device_id, teraz)
    delivery.podbij_pozycje(order, teraz)
    return True


def cofnij_weryfikacje_zamowienia(order, aktywne, aktualne, powod, worker_id, device_id, teraz):
    """Pozycje zweryfikowane → 'spakowane', znaczniki weryfikacji zamówienia i aktualnych paczek
    czyszczone (spec 4.5), log 'weryfikacja_cofnieta' z powodem. Wspólne dla „Cofnij weryfikację”
    i zgłoszenia problemu (Task 7). `aktywne` i `aktualne` pochodzą z stan_do_zapisu — paczki są już
    zablokowane i czytane bieżąco, więc funkcja nie czyta ich drugi raz (kolejność blokad: paczki
    przed zapisem pozycji)."""
    for p in aktywne:
        if p.current_status == 'zweryfikowane':
            p.current_status = 'spakowane'
    order.verified_at = None
    order.verified_by_worker_id = None
    for p in aktualne:
        p.verified_at = None
        p.verified_by_worker_id = None
        p.verified_method = None
    delivery.zapisz_log(order, 'weryfikacja_cofnieta', note=(powod or u'')[:255] or None,
                        worker_id=worker_id, device_id=device_id, teraz=teraz)
    delivery.przelicz_zamkniecie(order, teraz)
    delivery.podbij_pozycje(order, teraz)


def cofnij_weryfikacje(order, worker_id=None, device_id=None, teraz=None, powod=u'Cofnij weryfikację'):
    """„Cofnij weryfikację” (spec 4.5): tylko zamówienie zweryfikowane i niezaładowane."""
    teraz = teraz or get_local_now()
    aktywne, aktualne = stan_do_zapisu(order)
    if not all(p.current_status == 'zweryfikowane' for p in aktywne):
        raise WeryfikacjaBlad('order_not_verified', u'Zamówienie {} nie jest zweryfikowane.'.format(
            order.internal_order_number))
    sprawdz_zakres(order, teraz)
    cofnij_weryfikacje_zamowienia(order, aktywne, aktualne, powod, worker_id, device_id, teraz)
    return True


def _notatka(wartosc):
    """Notatka z JSON-a: tekst z pojedynczymi spacjami, najwyżej 255 znaków (dłuższa jest ucinana —
    422 z kolejki offline to utracona akcja); inny typ albo pusty tekst → None."""
    if not isinstance(wartosc, str):
        return None
    return ' '.join(wartosc.split())[:255] or None


def waliduj_powod(powod):
    # Typ sprawdzamy przed słownikiem: lista z JSON-a nie jest hashowalna (TypeError → 500, a 5xx
    # telefon ponawia bez końca), a błędny powód ma być 422 zapamiętanym przez idempotencję.
    if not isinstance(powod, str) or powod not in POWODY_PROBLEMU:
        raise WeryfikacjaBlad('invalid_problem', u'Powód problemu: {}.'.format(
            u', '.join(sorted(POWODY_PROBLEMU))), 422)
    return powod


def zglos_problem(order, powod, notatka, worker_id=None, device_id=None, teraz=None):
    """
    Zgłoszenie problemu (spec 8.3): tylko przed załadunkiem. Zamówienie zweryfikowane (albo z częścią
    sprawdzonych paczek) traci weryfikację — inaczej problem obszedłby bramkę załadunku. Ponowne
    zgłoszenie nadpisuje powód i notatkę. NIE commituje.
    """
    teraz = teraz or get_local_now()
    waliduj_powod(powod)
    notatka = _notatka(notatka)
    aktywne, aktualne = stan_do_zapisu(order)
    sprawdz_zakres(order, teraz)
    if (order.verified_at is not None or any(p.current_status == 'zweryfikowane' for p in aktywne)
            or any(p.verified_at is not None for p in aktualne)):
        cofnij_weryfikacje_zamowienia(order, aktywne, aktualne, u'problem: {}'.format(POWODY_PROBLEMU[powod]),
                                      worker_id, device_id, teraz)
    stary = order.problem_reason
    order.problem_reason = powod
    order.problem_note = notatka
    order.problem_at = teraz
    order.problem_by_worker_id = worker_id
    delivery.zapisz_log(order, 'problem', stary, powod, note=notatka, worker_id=worker_id,
                        device_id=device_id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return True


def rozwiaz_problem(order, worker_id=None, device_id=None, teraz=None, notatka=None):
    """Zdjęcie flagi problemu (spec 8.3). Bez problemu — False bez zmian (kolejka offline nie utyka)."""
    if order.problem_at is None:
        return False
    teraz = teraz or get_local_now()
    stary = order.problem_reason
    order.problem_reason = None
    order.problem_note = None
    order.problem_at = None
    order.problem_by_worker_id = None
    delivery.zapisz_log(order, 'problem_rozwiazany', stary, None, note=notatka, worker_id=worker_id,
                        device_id=device_id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return True


def cofnij_do_pakowania(order, powod=None, notatka=None, worker_id=None, device_id=None, teraz=None):
    """
    „Cofnij do pakowania” (spec 4.5 i 8.4) — jak przepakowanie z etapu 1: pozycje → czeka_na_pakowanie,
    licznik pakowania wyzerowany zdarzeniem systemowym, repack_required + repack_reason
    („Weryfikacja: <powód>: <notatka>”), Base. 138620 (dopychacz po commicie), paczki i weryfikacja
    unieważnione jedną regułą, otwarty problem przeniesiony do banera. Brak powodu w żądaniu → powód
    i notatka z otwartego problemu; podany powód bez notatki też bierze notatkę otwartego problemu
    (flaga problemu przenosi się do banera w całości). Zamówienie na trasie zostaje na niej.
    Stan pozycji i paczek czytany jest bieżąco (stan_do_zapisu) PRZED pętlą przestawiającą pozycje:
    pętla i `set_quantity_done` (delta zdarzenia stanowiska) pracują na świeżych wartościach, a reguła
    uniewaznij_etapy bierze już posiadane blokady paczek. Zwraca tekst banera.
    """
    teraz = teraz or get_local_now()
    notatka = _notatka(notatka)
    if order.problem_at is not None:
        powod = powod or order.problem_reason
        notatka = notatka or order.problem_note
    if not powod:
        raise WeryfikacjaBlad('invalid_problem', u'Podaj powód cofnięcia do pakowania.', 422)
    waliduj_powod(powod)
    aktywne, _aktualne = stan_do_zapisu(order)
    sprawdz_zakres(order, teraz)   # przed pierwszym zapisem i przed zaplanowaniem dopychacza Base.
    przed, _napis = etap(aktywne)
    tekst = (u'Weryfikacja: {}'.format(POWODY_PROBLEMU[powod])
             + (u': {}'.format(notatka) if notatka else u''))[:255]
    for p in aktywne:
        # Zdarzenie systemowe bez atrybucji — jak przepakowanie w delivery.ustaw_sposob_dostawy.
        p.set_quantity_done('packaging', 0, source='system')
        p.packaging_completed_at = None
        p.current_status = 'czeka_na_pakowanie'
    order.repack_required = True
    order.repack_reason = tekst
    order.bl_status_pending_id = sposoby.STATUS_PRODUKCJA_ZAKONCZONA
    if order.problem_at is not None:
        rozwiaz_problem(order, worker_id, device_id, teraz, notatka=u'przeniesiony do banera pakowania')
    delivery.zapisz_log(order, 'cofniete_do_pakowania', przed, 'czeka_na_pakowanie', note=tekst,
                        worker_id=worker_id, device_id=device_id, teraz=teraz)
    uniewaznij_etapy(order, teraz, u'cofnięte do pakowania', worker_id=worker_id, device_id=device_id)
    delivery.przelicz_zamkniecie(order, teraz)
    delivery.podbij_pozycje(order, teraz)
    from modules.production.logistics.services import bl_sync
    bl_sync.zaplanuj_po_commicie(order.id)
    return tekst
