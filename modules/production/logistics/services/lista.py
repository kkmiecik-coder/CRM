# -*- coding: utf-8 -*-
"""Lista zamówień zakładki Logistyka (spec, sekcja 6.7)."""
import re

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.services import geocoding
from modules.production.logistics.services.delivery import aktywne_produkty, wszystkie_spakowane
from modules.production.models import ProductionOrder, ProductionProduct
from modules.production.services.station_catalog import STATION_LABELS, STATION_PENDING_STATUS

# Najwcześniejszy etap zamówienia = etap jego najbardziej zaległej pozycji.
KOLEJNOSC_ETAPOW = ('wstrzymane', 'czeka_na_wyciecie', 'czeka_na_skladanie',
                    'czeka_na_sklejanie', 'czeka_na_formatowanie', 'czeka_na_krawedzie',
                    'czeka_na_lakiernie', 'czeka_na_pakowanie', 'spakowane')
LIMIT_ZAMKNIETYCH = 50

# Etap w kolumnie listy = STANOWISKO, na którym pozycja czeka („Lakiernia”, nie
# „Czeka na lakiernię”) — nazwy z jednego źródła (station_catalog), tymi samymi
# mówią monitory na hali. Statusy spoza kolejek (spakowane, wstrzymane) — jak w bazie.
NAZWA_STANOWISKA = {status: STATION_LABELS[kod] for kod, status in STATION_PENDING_STATUS.items()}


def _ranga(status):
    """
    Status spoza KOLEJNOSC_ETAPOW (np. `czeka_na_logistyke` zapisany przez stary kod
    w oknie wdrożenia) dostaje rangę -1, czyli wychodzi jako NAJWCZEŚNIEJSZY etap —
    anomalia ma być widoczna, a nie chować się za „Spakowane”.
    """
    return KOLEJNOSC_ETAPOW.index(status) if status in KOLEJNOSC_ETAPOW else -1


def warunek_bez_sposobu():
    """
    „Nie ustawiono” w SQL — ta sama definicja co sposoby.normalizuj() w Pythonie
    (licznik zakładki, 409 tabletu): NULL albo wartość spoza SPOSOBY (np. pusty tekst).
    Używają jej filtr `sposob=brak` i bramka dashboardu produkcji.
    """
    kolumna = ProductionOrder.override_delivery_method
    return or_(kolumna.is_(None), kolumna.notin_(sposoby.SPOSOBY))


def liczba_bez_sposobu():
    """Bramka dashboardu produkcji: otwarte zamówienia z aktywną pozycją i bez sposobu."""
    return db.session.query(func.count(ProductionOrder.id)).filter(
        ProductionOrder.logistics_closed_at.is_(None),
        warunek_bez_sposobu(),
        ProductionOrder.products.any(ProductionProduct.current_status != 'anulowane'),
    ).scalar() or 0


def _wzor_like(fraza):
    """`%`, `_` i sam znak ucieczki `\\` dosłownie (ESCAPE '\\'), nie jako wieloznaczniki."""
    bezpieczna = fraza.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return u'%{}%'.format(bezpieczna)


# Pola wyszukiwarki: numer, klient, ulica z numerem, kod pocztowy, miejscowość.
_POLA_FRAZY = (ProductionOrder.internal_order_number, ProductionOrder.client_name,
               ProductionOrder.delivery_address, ProductionOrder.delivery_postcode,
               ProductionOrder.delivery_city)
MAKS_SLOW_FRAZY = 6


def _warunki_frazy(fraza):
    """
    Każde słowo frazy musi pasować do któregoś pola (niekoniecznie tego samego):
    „Kowalski Rzeszów”, „Zagłoby 10 Józefów”. Pięć cyfr to też kod z kreską
    („35310” znajduje „35-310”).
    """
    warunki = []
    for slowo in fraza.split()[:MAKS_SLOW_FRAZY]:
        wzory = [_wzor_like(slowo)]
        if re.fullmatch(r'\d{5}', slowo):
            wzory.append(_wzor_like(slowo[:2] + '-' + slowo[2:]))
        warunki.append(or_(*[pole.ilike(wzor, escape='\\')
                             for pole in _POLA_FRAZY for wzor in wzory]))
    return warunki


def _etap(aktywne):
    if not aktywne:
        return {'status': 'anulowane', 'nazwa': 'Anulowane'}
    najwczesniejszy = min(aktywne, key=lambda p: _ranga(p.current_status))
    status = najwczesniejszy.current_status
    return {'status': status,
            'nazwa': NAZWA_STANOWISKA.get(status) or najwczesniejszy.status_display_name}


def _geo(punkt):
    if punkt is None or punkt.lat is None:
        return None
    return {'lat': float(punkt.lat), 'lng': float(punkt.lng), 'quality': punkt.quality,
            'source': punkt.source, 'adres_zmieniony': bool(punkt.address_changed_after_manual)}


def _liczba(wartosc):
    """Decimal z bazy → '4' albo '4.5' (bez zbędnych zer), None → None."""
    if wartosc is None:
        return None
    return format(float(wartosc), 'g')


def _pozycja(p):
    """
    Pozycja zamówienia do rozwijanego wiersza listy — to samo, co pokazuje lista
    produktów (nazwa, ID, gatunek / technologia / klasa / grubość, ilość, m³),
    plus etap jako stanowisko (jak kolumna „Etap produkcji”).
    """
    konfiguracja = p.configuration

    def cecha(nazwa):
        # find_or_create zapisuje „unknown” dla usług i nieparsowalnych nazw — lista
        # produktów go nie pokazuje, więc i tu nie (przegląd D18).
        wartosc = getattr(konfiguracja, nazwa, None) if konfiguracja else None
        return None if wartosc in (None, '', 'unknown') else wartosc

    return {
        'id': p.short_product_id,
        'nazwa': p.original_product_name,
        'gatunek': cecha('species'),
        'technologia': cecha('technology'),
        'klasa': cecha('wood_class'),
        'grubosc_cm': _liczba(p.parsed_thickness_cm),
        'bez_dociecia': p.cut_to_size is False,
        'dorobka': p.original_product_id is not None,
        'ilosc': p.quantity or 1,
        'm3': round(float(p.volume_m3 or 0) * (p.quantity or 1), 4),
        'etap': {'status': p.current_status,
                 'nazwa': NAZWA_STANOWISKA.get(p.current_status) or p.status_display_name},
        'anulowana': p.current_status == 'anulowane',
    }


def serializuj(order, geo=None):
    aktywne = aktywne_produkty(order)
    sposob = sposoby.normalizuj(order.override_delivery_method)
    terminy = [p.deadline_date for p in aktywne if p.deadline_date]
    ustawiono = order.delivery_method_set_at
    return {
        'id': order.id,
        'numer': order.internal_order_number,
        'baselinker_order_id': order.baselinker_order_id,
        'klient': order.client_name,
        'miasto': order.delivery_city,
        'kod': order.delivery_postcode,
        'adres': order.delivery_address,
        'metoda_z_base': order.delivery_method,
        'podpowiedz': sposoby.podpowiedz(order),
        'sposob': sposob,
        'sposob_etykieta': sposoby.etykieta(sposob),
        'etap': _etap(aktywne),
        'termin': min(terminy).isoformat() if terminy else None,
        'm3': round(sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in aktywne), 4),
        'spakowane': wszystkie_spakowane(order),
        'wydane': order.handed_over_at.isoformat() if order.handed_over_at else None,
        'zamkniete': order.logistics_closed_at is not None,
        'base_czeka': bool(order.bl_delivery_method_pending or order.bl_status_pending_id
                           or order.bl_address_pending),
        'etykiety_sprzed_zmiany': bool(ustawiono) and any(
            p.label_printed_at is not None and p.label_printed_at < ustawiono for p in aktywne),
        'przepakowanie': bool(order.repack_required),
        # Rozwijany wiersz listy: wszystkie pozycje (anulowane też — wyszarzone).
        'pozycje': [_pozycja(p) for p in sorted(
            order.products, key=lambda p: (p.product_sequence_in_order or 0, p.id or 0))],
        'geo': _geo(geo),
    }


def _klucz(wiersz):
    return (wiersz['sposob'] is not None, wiersz['termin'] is None,
            wiersz['termin'] or '', wiersz['numer'] or '')


def pobierz(sposob=None, etap=None, q=None, zamkniete=False):
    """
    UWAGA (R3, poprawka względem briefu): wszystkie filtry (q, otwarte/zamknięte,
    sposob) muszą trafić do zapytania PRZED order_by/limit. W SQLAlchemy < 2.0
    Query.filter() wołane PO limit() rzuca InvalidRequestError — pierwotna wersja
    (limit dla zamkniętych, potem filter dla sposob) wywalałaby się na
    GET /orders?zamkniete=1&q=...&sposob=... kodem 500.
    """
    # Konfiguracje pozycji (gatunek, technologia, klasa) jednym zapytaniem na listę —
    # bez tego każda pozycja dociągałaby swoją osobno (setki zapytań co odświeżenie).
    zapytanie = ProductionOrder.query.options(
        selectinload(ProductionOrder.products).selectinload(ProductionProduct.configuration))
    if q:
        zapytanie = zapytanie.filter(*_warunki_frazy(q))
    if not zamkniete:
        zapytanie = zapytanie.filter(ProductionOrder.logistics_closed_at.is_(None))
    if sposob == 'brak':
        zapytanie = zapytanie.filter(warunek_bez_sposobu())
    elif sposoby.normalizuj(sposob):
        zapytanie = zapytanie.filter(ProductionOrder.override_delivery_method == sposob)
    if zamkniete:
        zapytanie = zapytanie.order_by(ProductionOrder.id.desc()).limit(LIMIT_ZAMKNIETYCH)
    zamowienia = zapytanie.all()
    punkty = geocoding.geo_zamowien([o.id for o in zamowienia])
    wiersze = [serializuj(o, punkty.get(o.id)) for o in zamowienia]
    if etap:
        wiersze = [w for w in wiersze if w['etap']['status'] == etap]
    return sorted(wiersze, key=_klucz)


def liczniki():
    wynik = {'brak': 0, sposoby.KURIER: 0, sposoby.TRANSPORT: 0, sposoby.ODBIOR: 0}
    for (wartosc,) in (ProductionOrder.query.with_entities(ProductionOrder.override_delivery_method)
                       .filter(ProductionOrder.logistics_closed_at.is_(None)).all()):
        klucz = sposoby.normalizuj(wartosc) or 'brak'
        wynik[klucz] += 1
    return wynik
