# -*- coding: utf-8 -*-
"""
Paczki zamówienia (logistyka etap 4, krok 4.2, spec 5.2 i 7).

Paczka = paczka albo paleta zadeklarowana przy pakowaniu; kod na etykiecie i w QR to
'P-<id>'. Aktualna deklaracja zamówienia = jego paczki z voided_at IS NULL. Funkcje
NIE commitują — robi to wołający (API mobilne przez @with_idempotency).
"""
from modules.production.logistics import sposoby
from modules.production.models import ProductionPackage


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


def serializuj_paczke(p):
    """Paczka w API mobilnym (kontrakt kroku 4.2; krok 4.3 dołoży stan weryfikacji)."""
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
    }
