# -*- coding: utf-8 -*-
"""
Sposoby dostawy — JEDYNE miejsce, które tłumaczy wartość
prod_orders.override_delivery_method na wszystko, co z niej wynika: tryb dla
tabletu, stare delivery_type, tekst do Base., status Base. po spakowaniu
i napis na plakietce/etykiecie.

Moduł celowo nie importuje niczego z aplikacji — czytają go models.py,
baselinker_status_sync.py i API mobilne, więc import z nich tworzyłby cykle.
"""

KURIER = 'kurier_baselinker'
TRANSPORT = 'transport_woodpower'
ODBIOR = 'odbior_osobisty'
SPOSOBY = (KURIER, TRANSPORT, ODBIOR)

# Obiekt `transport.mode` w API mobilnym (kontrakt uzgodniony z appką).
MODE = {KURIER: 'kurier', TRANSPORT: 'wlasny', ODBIOR: 'odbior'}

# Stare pole `delivery_type` — tylko wartości, które znają dzisiejsze APK.
LEGACY_DELIVERY_TYPE = {KURIER: 'courier', TRANSPORT: 'transport_woodpower',
                        ODBIOR: 'personal_pickup'}

# Tekst pola „Metoda dostawy" w Base. — zawsze nadpisujemy (decyzja 24.09).
TEKST_BASE = {KURIER: 'Kurier', TRANSPORT: 'Transport WoodPower',
              ODBIOR: 'Odbiór osobisty'}

STATUS_PRODUKCJA_ZAKONCZONA = 138620
STATUS_SPAKOWANE = 138623
STATUS_PLANOWANA_TRASA = 417343
STATUS_CZEKA_NA_ODBIOR = 149777
STATUS_ODEBRANE = 149779
# Furtka pod stanowisko kierowcy — w etapie 1 nikt ich nie ustawia.
STATUS_WYSLANE_TRANSPORT = 149763
STATUS_DOSTARCZONE_TRANSPORT = 149778

STATUS_PO_SPAKOWANIU = {KURIER: STATUS_SPAKOWANE, TRANSPORT: STATUS_PLANOWANA_TRASA,
                        ODBIOR: STATUS_CZEKA_NA_ODBIOR}

NIE_USTAWIONO = 'Nie ustawiono'
_ETYKIETA = {KURIER: 'Kurier', TRANSPORT: 'Transport WoodPower', ODBIOR: 'Odbiór osobisty'}


def normalizuj(wartosc):
    """Wartość z bazy albo z żądania → jedna z SPOSOBY albo None."""
    if wartosc is None:
        return None
    w = str(wartosc).strip()
    return w if w in SPOSOBY else None


def etykieta(sposob, nazwa_trasy=None):
    """Napis dla człowieka: plakietka tabletu, linia „Dostawa:" na etykiecie, lista."""
    s = normalizuj(sposob)
    if s is None:
        return NIE_USTAWIONO
    if s == TRANSPORT and nazwa_trasy:
        return nazwa_trasy
    return _ETYKIETA[s]


def legacy_delivery_type(sposob):
    """Brak sposobu → 'courier': stare APK pokażą „KURIER" (świadomie, okres przejściowy)."""
    return LEGACY_DELIVERY_TYPE.get(normalizuj(sposob), 'courier')


def transport_payload(order, trasa=None):
    """
    Obiekt `transport` API mobilnego. ZAWSZE słownik, nigdy None — brak obiektu
    oznacza dla appki stary backend (brak blokady pakowania).
    `trasa` dochodzi w etapie 3; do tego czasu pola trip_* są puste.
    """
    sposob = normalizuj(getattr(order, 'override_delivery_method', None)) if order is not None else None
    pojazd = getattr(trasa, 'vehicle', None) if trasa is not None else None
    data = getattr(trasa, 'date_from', None) if trasa is not None else None
    return {
        'mode': MODE.get(sposob),
        'trip_name': trasa.name if trasa is not None else None,
        'trip_date': data.isoformat() if data is not None else None,
        'vehicle_name': pojazd.name if pojazd is not None else None,
        'repack_required': bool(getattr(order, 'repack_required', False)) if order is not None else False,
    }


def podpowiedz(order):
    """Sposób, który sugeruje metoda dostawy z Base. — tylko podpowiedź dla logistyka."""
    tekst = (getattr(order, 'delivery_method', None) or '').lower()
    if getattr(order, 'is_personal_pickup', False):
        return ODBIOR
    if 'transport' in tekst and ('woodpower' in tekst or 'wood power' in tekst
                                 or 'własny' in tekst or 'wlasny' in tekst or 'nasz' in tekst):
        return TRANSPORT
    return KURIER
