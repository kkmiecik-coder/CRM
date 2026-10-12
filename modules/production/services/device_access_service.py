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

from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import ProductionDevice, get_local_now
from modules.production.services.station_catalog import resolve_station_code

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


# ============================================================================
# REJESTRACJA (POST /api/mobile/register) — spec sekcja 4, kontrakt sekcja 3
# ============================================================================

def _tekst(wartosc):
    """Pole tekstowe z body: napis po strip(); wszystko inne (None, liczba, lista) → '' (dalej: 400, nie 500)."""
    return wartosc.strip() if isinstance(wartosc, str) else ''


def zarejestruj_albo_popros(dane, ip=None, app_version=None):
    """
    Maszyna stanów rejestracji. Zwraca `(kod_http, body)`; commituje sama (obsługuje wyścig dwóch pierwszych żądań).

    nieznane device_id → prośba `oczekuje` (202) | `oczekuje` → odświeżenie prośby (202) |
    `zatwierdzone` → token jak dotąd, w tym zmiana stanowiska (200) | `zablokowane` → 403, bez żadnej zmiany.
    """
    if not isinstance(dane, dict):
        dane = {}
    device_id = _tekst(dane.get('device_id'))
    nazwa = _tekst(dane.get('device_name'))
    model = _tekst(dane.get('device_model'))
    # Stary APK przedstawia się kodem 'finishing'. Bez rozwinięcia aliasu tutaj każde odnowienie JWT odtwarzałoby
    # w prod_devices wiersz, który migracja przed chwilą poprawiła — a po zdjęciu 'finishing' z VALID_STATION_CODES
    # stary tablet dostałby 400 invalid_station_code i nie odnowiłby tokenu w ogóle. Rozwinięcie stoi PRZED walidacją
    # kompletności pól (kontrakt resolve_station_code z nagłówka planu wdrożenia podziału Wykańczania).
    station_code = resolve_station_code(_tekst(dane.get('station_code')))

    if not device_id or not station_code:
        return 400, {'error': 'missing_fields', 'required': ['device_id', 'station_code']}
    if station_code not in ProductionDevice.VALID_STATION_CODES:
        return 400, {'error': 'invalid_station_code', 'allowed': sorted(ProductionDevice.VALID_STATION_CODES)}
    for pole, wartosc, limit in (('device_id', device_id, MAX_DEVICE_ID), ('device_name', nazwa, MAX_NAZWA),
                                 ('device_model', model, MAX_MODEL)):
        if len(wartosc) > limit:
            return 400, {'error': 'field_too_long', 'field': pole}

    mac = None
    if dane.get('mac_address') not in (None, ''):
        mac = normalizuj_mac(dane.get('mac_address'))
        if mac is None:
            return 400, {'error': 'mac_invalid'}

    prosba = {'device_id': device_id, 'nazwa': nazwa, 'station_code': station_code, 'model': model, 'mac': mac,
              'ip': ip, 'app_version': app_version}
    return _wedlug_stanu(prosba, ponowienie=False)


def _wedlug_stanu(prosba, ponowienie):
    device = ProductionDevice.query.filter_by(device_id=prosba['device_id']).first()
    if device is None:
        return _nowa_prosba(prosba, ponowienie)
    if device.status == OCZEKUJE:
        if prosba['mac'] is None:
            return 400, {'error': 'mac_required'}
        _uzupelnij_prosbe(device, prosba)
        db.session.commit()
        logger.info('Urządzenia: prośba odświeżona', extra=_do_logu('device_request_refreshed', device, prosba))
        return 202, _tresc_oczekuje(device)
    if device.status != ZATWIERDZONE or not device.is_active:
        logger.warning('Urządzenia: rejestracja zablokowanego', extra=_do_logu('device_register_blocked', device, prosba))
        return 403, {'error': 'device_blocked', 'retry_after_s': PONOW_PO_S_ZABLOKOWANE}

    # Zatwierdzone: jak dotąd (zmiana stanowiska z bramki „Kto pracuje?”, cicha naprawa po 401). Nazwy z urządzenia
    # nie przyjmujemy — nadaje ją admin przy zatwierdzaniu.
    from modules.production.services.mobile_api_service import generate_token
    device.station_code = prosba['station_code']
    if prosba['model']:
        device.device_model = prosba['model']
    zapisz_zgloszony_mac(device, prosba['mac'])
    db.session.commit()
    token = generate_token(device)
    logger.info('Urządzenia: wydano token', extra=_do_logu('device_token_issued', device, prosba))
    return 200, {'status': 'approved', 'token': token, 'device_id': device.device_id,
                 'station_code': device.station_code, 'device_name': device.device_name}


def _nowa_prosba(prosba, ponowienie):
    if prosba['mac'] is None:
        return 400, {'error': 'mac_required'}
    usun_przeterminowane_prosby()
    if ProductionDevice.query.filter_by(status=OCZEKUJE).count() >= MAX_OCZEKUJACYCH:
        db.session.commit()  # zatwierdza skasowanie przeterminowanych
        logger.warning('Urządzenia: limit oczekujących próśb', extra={
            'event': 'device_request_limit', 'ip': prosba['ip'], 'mac': prosba['mac']})
        return 429, {'error': 'too_many_pending', 'retry_after_s': PONOW_PO_S_LIMIT}
    device = ProductionDevice(device_id=prosba['device_id'], station_code=prosba['station_code'])
    ustaw_status(device, OCZEKUJE)
    _uzupelnij_prosbe(device, prosba)
    db.session.add(device)
    try:
        db.session.commit()
    except IntegrityError:
        # Równoległe pierwsze żądanie tego samego device_id zdążyło z INSERT-em (unikalny device_id).
        db.session.rollback()
        if ponowienie:
            raise
        return _wedlug_stanu(prosba, ponowienie=True)
    logger.info('Urządzenia: nowa prośba o dostęp', extra=_do_logu('device_request_created', device, prosba))
    return 202, _tresc_oczekuje(device)


def _uzupelnij_prosbe(device, prosba):
    device.station_code = prosba['station_code']
    device.device_name = prosba['nazwa'] or None
    device.device_model = prosba['model'] or None
    device.mac_address = prosba['mac']
    device.requested_at = get_local_now()
    if prosba['ip']:
        device.last_ip = prosba['ip'][:45]
    if prosba['app_version']:
        device.app_version = prosba['app_version'][:32]


def _tresc_oczekuje(device):
    return {'status': 'pending', 'device_id': device.device_id, 'mac_address': device.mac_address,
            'retry_after_s': PONOW_PO_S_OCZEKUJE}


def _do_logu(zdarzenie, device, prosba):
    return {'event': zdarzenie, 'device_id': device.device_id, 'station_code': device.station_code,
            'mac': prosba['mac'], 'ip': prosba['ip']}
