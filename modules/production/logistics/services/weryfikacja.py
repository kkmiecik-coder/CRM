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
from modules.production.models import ProductionConfig, ProductionOrder, ProductionProduct
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


def uniewaznij_etapy(order, teraz, powod, user_id=None, worker_id=None, device_id=None):
    """
    Jedna reguła (spec 4.5, ostatni wiersz, i 8.5): zamówienie, którego któraś niezanulowana pozycja
    nie jest „spakowane lub dalej” (doróbka, nowa pozycja z Base., przepakowanie, cofnięcie do
    pakowania, ręczna zmiana statusu), traci paczki (unieważnione razem z oczekującymi zadaniami
    druku), weryfikację i załadunek, a jego pozycje zweryfikowane i załadowane wracają do
    'spakowane'. Po ponownym spakowaniu zamówienie przechodzi kroki od nowa.

    `powod` — tekst do logu i komunikatu wygaszonego zadania druku (np. u'nowa pozycja z Base.').
    Zwraca True, gdy coś zmieniła. Gdy nie ma czego kasować, nie pyta bazy (czyta kolumny zamówienia
    i statusy już wczytanych pozycji) — woła ją cron dla każdego otwartego zamówienia. NIE commituje.

    Kolejność blokad: najpierw zapis wiersza zamówienia (flush), potem paczki (odczyt blokujący) —
    ta sama kolejność co w deklaracji i akcjach Weryfikacji (zamówienie → paczki), więc nie tworzy
    z nimi cyklu. Globalnej blokady deklaracji NIE bierze: wołający (panel, synchronizacja, tablet)
    trzymają już inne blokady, a wiersz blokady musiałby być pierwszy.

    Wymagania wobec wołającego: reguła decyduje na stanie W PAMIĘCI (packages_declared_at, verified_at,
    statusy pozycji), więc zamówienie ma być wczytane odczytem bieżącym (po blokadzie wiersza zamówienia,
    nie z migawki sprzed niej), a wołający nie zapisuje pozycji przed tą blokadą. „Bez zapytań” zachodzi
    tylko przy już wczytanych pozycjach (cron ładuje je przez selectinload) — inaczej samo
    `order.products` jest zapytaniem.
    """
    aktywne = delivery.aktywne_produkty(order)
    if not aktywne or all(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne):
        return False
    cofane = [p for p in aktywne if p.current_status in _COFANE_DO_SPAKOWANYCH]
    if order.packages_declared_at is None and order.verified_at is None and not cofane:
        return False
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
        db.session.flush()   # wiersz zamówienia przed paczkami (kolejność blokad — docstring)
        stare = paczki.aktualne_paczki(order.id, do_zapisu=True)
        paczki.uniewaznij(stare, teraz, powod=notatka or u'unieważnienie etapów')
        delivery.zapisz_log(order, 'paczki', paczki.opis_paczek(stare), None, note=notatka,
                            user_id=user_id, worker_id=worker_id, device_id=device_id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return True
