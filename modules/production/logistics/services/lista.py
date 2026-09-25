# -*- coding: utf-8 -*-
"""Lista zamówień zakładki Logistyka (spec, sekcja 6.7)."""
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.services import geocoding
from modules.production.logistics.services.delivery import aktywne_produkty, wszystkie_spakowane
from modules.production.models import ProductionOrder, ProductionProduct

# Najwcześniejszy etap zamówienia = etap jego najbardziej zaległej pozycji.
KOLEJNOSC_ETAPOW = ('wstrzymane', 'czeka_na_wyciecie', 'czeka_na_skladanie',
                    'czeka_na_sklejanie', 'czeka_na_formatowanie', 'czeka_na_krawedzie',
                    'czeka_na_lakiernie', 'czeka_na_pakowanie', 'spakowane')
LIMIT_ZAMKNIETYCH = 50


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


def _etap(aktywne):
    if not aktywne:
        return {'status': 'anulowane', 'nazwa': 'Anulowane'}
    najwczesniejszy = min(aktywne, key=lambda p: _ranga(p.current_status))
    return {'status': najwczesniejszy.current_status,
            'nazwa': najwczesniejszy.status_display_name}


def _geo(punkt):
    if punkt is None or punkt.lat is None:
        return None
    return {'lat': float(punkt.lat), 'lng': float(punkt.lng), 'quality': punkt.quality,
            'source': punkt.source, 'adres_zmieniony': bool(punkt.address_changed_after_manual)}


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
        'base_czeka': bool(order.bl_delivery_method_pending or order.bl_status_pending_id),
        'etykiety_sprzed_zmiany': bool(ustawiono) and any(
            p.label_printed_at is not None and p.label_printed_at < ustawiono for p in aktywne),
        'przepakowanie': bool(order.repack_required),
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
    zapytanie = ProductionOrder.query.options(selectinload(ProductionOrder.products))
    if q:
        wzor = _wzor_like(q.strip())
        zapytanie = zapytanie.filter(or_(
            ProductionOrder.internal_order_number.ilike(wzor, escape='\\'),
            ProductionOrder.client_name.ilike(wzor, escape='\\'),
            ProductionOrder.delivery_city.ilike(wzor, escape='\\')))
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
