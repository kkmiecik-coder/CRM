# -*- coding: utf-8 -*-
"""
Dostęp urządzeń mobilnych po zatwierdzeniu przez admina
(spec docs/superpowers/specs/2026-10-12-urzadzenia-mobilne-zatwierdzanie-design.md, kontrakt docs/api-mobile-urzadzenia.md).

Urządzenie zgłasza prośbę z MAC-iem (`register`), admin zatwierdza ją w zakładce „Urządzenia mobilne”, a dopiero
zatwierdzone dostaje JWT. MAC jest identyfikatorem dla człowieka, nie sekretem — bramką jest zatwierdzenie.

`prod_devices.status` jest źródłem prawdy, `is_active` jego pochodną; oba zmienia wyłącznie `ustaw_status()`.
Funkcje nie commitują — commituje wołający (wyjątek: `zarejestruj_albo_popros`, która obsługuje wyścig INSERT-ów).
"""
import re
from datetime import timedelta

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import ProductionDevice, get_local_now

logger = get_structured_logger('production.device_access')

OCZEKUJE = ProductionDevice.STATUS_OCZEKUJE
ZATWIERDZONE = ProductionDevice.STATUS_ZATWIERDZONE
ZABLOKOWANE = ProductionDevice.STATUS_ZABLOKOWANE

MAX_OCZEKUJACYCH = 20
WAZNOSC_PROSBY_DNI = 7
# Wartości `retry_after_s` w odpowiedziach 202 / 403 / 429 rejestracji.
PONOW_PO_S_OCZEKUJE = 5
PONOW_PO_S_ZABLOKOWANE = 30
PONOW_PO_S_LIMIT = 60

# Długości kolumn prod_devices — dłuższe pole w prośbie to 400 field_too_long, nie obcięcie po cichu.
MAX_DEVICE_ID = 64
MAX_NAZWA = 128
MAX_MODEL = 64

# Atrapa, którą Android od wersji 6 oddaje zwykłej appce zamiast MAC-u, i adres zerowy.
_ATRAPY_MAC = frozenset({'02:00:00:00:00:00', '00:00:00:00:00:00'})
_SZESNASTKOWE_12 = re.compile(r'^[0-9A-F]{12}$')


def normalizuj_mac(surowy):
    """
    MAC z wejścia → `AA:BB:CC:DD:EE:FF` albo None. Akceptuje separatory `:` i `-` (albo ich brak) i dowolną wielkość
    liter. Odrzuca wszystko, co nie jest 12 cyframi szesnastkowymi, atrapę Androida i adres zerowy. Wartość
    nie-tekstowa (liczba, lista, None) → None, bez wyjątku.
    """
    if not isinstance(surowy, str):
        return None
    cyfry = re.sub(r'[:\-]', '', surowy.strip()).upper()
    if not _SZESNASTKOWE_12.match(cyfry):
        return None
    mac = ':'.join(cyfry[i:i + 2] for i in range(0, 12, 2))
    return None if mac in _ATRAPY_MAC else mac


def ustaw_status(device, status, user_id=None):
    """
    Jedyne miejsce zmiany `status` i `is_active`. Blokada podbija `token_version` (stare JWT przestają działać od
    razu) i zapisuje kto/kiedy; zatwierdzenie zapisuje kto/kiedy tylko przy pierwszym zatwierdzeniu i czyści blokadę.
    """
    if status not in ProductionDevice.STATUSY:
        raise ValueError(f'Nieznany status urządzenia: {status!r}')
    teraz = get_local_now()
    device.status = status
    device.is_active = (status == ZATWIERDZONE)
    if status == ZATWIERDZONE:
        if device.approved_at is None:
            device.approved_at = teraz
            device.approved_by = user_id
        device.blocked_at = None
        device.blocked_by = None
    elif status == ZABLOKOWANE:
        device.blocked_at = teraz
        device.blocked_by = user_id
        device.revoke_tokens()


def zapisz_zgloszony_mac(device, mac):
    """
    MAC zgłoszony przez urządzenie (heartbeat, rejestracja zatwierdzonego). Pusty `mac_address` → uzupełnia; inny niż
    zapisany → `mac_conflict` do decyzji admina („Przyjmij nowy MAC”), bez blokowania — bramką jest zatwierdzenie.
    """
    if mac is None:
        return
    if device.mac_address is None:
        device.mac_address = mac
        return
    if device.mac_address == mac or device.mac_conflict == mac:
        return
    device.mac_conflict = mac
    logger.warning('Urządzenia: zgłoszony MAC różni się od zapisanego', extra={
        'event': 'device_mac_conflict',
        'device_pk': device.id,
        'mac_zapisany': device.mac_address,
        'mac_zgloszony': mac,
    })


def usun_przeterminowane_prosby(teraz=None):
    """Kasuje prośby nieodświeżane dłużej niż WAZNOSC_PROSBY_DNI. Zwraca liczbę skasowanych; nie commituje."""
    granica = (teraz or get_local_now()) - timedelta(days=WAZNOSC_PROSBY_DNI)
    return ProductionDevice.query.filter(
        ProductionDevice.status == OCZEKUJE,
        ProductionDevice.requested_at < granica,
    ).delete(synchronize_session=False)
