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
from modules.production.services.station_catalog import resolve_station_code, station_label

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


# ============================================================================
# PANEL „URZĄDZENIA MOBILNE” — spec sekcja 5. Funkcje nie commitują; commituje router.
# ============================================================================

class BladPanelu(Exception):
    """Odmowa akcji panelu: kod maszynowy, komunikat po polsku i status HTTP."""

    def __init__(self, kod, komunikat, status):
        super().__init__(komunikat)
        self.kod = kod
        self.komunikat = komunikat
        self.status = status


def _stan_zmieniony():
    return BladPanelu('stan_zmieniony', 'Stan urządzenia zmienił się w międzyczasie — odśwież listę.', 409)


def _wiersz_do_zapisu(pk):
    """Wiersz urządzenia odczytem bieżącym z blokadą — decyzja akcji zapada na tym odczycie."""
    device = (ProductionDevice.query.filter_by(id=pk)
              .with_for_update().populate_existing().first())
    if device is None:
        raise BladPanelu('nie_znaleziono', 'Nie ma takiego urządzenia ani prośby — odśwież listę.', 404)
    return device


def _poprawna_nazwa(nazwa):
    nazwa = nazwa.strip() if isinstance(nazwa, str) else ''
    if not nazwa or len(nazwa) > MAX_NAZWA:
        raise BladPanelu('nazwa_niepoprawna', f'Nazwa urządzenia musi mieć od 1 do {MAX_NAZWA} znaków.', 400)
    return nazwa


def _iso(chwila):
    return chwila.isoformat() if chwila else None


def _wspolne(d):
    return {
        'id': d.id,
        'nazwa': d.device_name,
        'stanowisko': d.station_code,
        'stanowisko_nazwa': station_label(d.station_code),
        'mac': d.mac_address,
        'model': d.device_model,
        'wersja': d.app_version,
        'wersja_kod': d.last_app_version_code,
        'ip': d.last_ip,
    }


def _ostatnio(d):
    sygnaly = [c for c in (d.last_seen_at, d.last_heartbeat_at) if c]
    return _iso(max(sygnaly)) if sygnaly else None


def _to_samo_co(d, po_mac):
    return [{'nazwa': o.device_name or '(bez nazwy)', 'status': o.status}
            for o in po_mac.get(d.mac_address, []) if o.id != d.id]


def _proponowana_nazwa(d, po_mac):
    """Przy reinstalacji — nazwa zatwierdzonego urządzenia o tym samym MAC-u, inaczej nazwa z prośby."""
    for o in po_mac.get(d.mac_address, []):
        if o.id != d.id and o.status == ZATWIERDZONE and o.device_name:
            return o.device_name
    return d.device_name


def _nazwy_uzytkownikow(ids):
    if not ids:
        return {}
    from modules.users.models import User
    return {u.id: u.get_full_name() for u in User.query.filter(User.id.in_(ids)).all()}


def lista_dla_panelu(teraz=None):
    """Trzy listy zakładki. Bez `device_id` — identyfikuje urządzenie przy rejestracji, nie wynosimy go do przeglądarki."""
    granica = (teraz or get_local_now()) - timedelta(days=WAZNOSC_PROSBY_DNI)
    wszystkie = ProductionDevice.query.order_by(ProductionDevice.id).all()
    po_mac = {}
    for d in wszystkie:
        if d.mac_address:
            po_mac.setdefault(d.mac_address, []).append(d)
    autorzy = _nazwy_uzytkownikow({d.approved_by for d in wszystkie if d.approved_by})

    prosby, urzadzenia, zablokowane = [], [], []
    for d in wszystkie:
        if d.status == OCZEKUJE:
            if d.requested_at is None or d.requested_at < granica:
                continue
            prosby.append({**_wspolne(d), 'zgloszono': _iso(d.requested_at),
                           'to_samo_co': _to_samo_co(d, po_mac), 'proponowana_nazwa': _proponowana_nazwa(d, po_mac)})
        elif d.status == ZATWIERDZONE:
            urzadzenia.append({**_wspolne(d), 'mac_conflict': d.mac_conflict, 'ostatnio': _ostatnio(d),
                               'zatwierdzone': _iso(d.approved_at), 'zatwierdzil': autorzy.get(d.approved_by)})
        else:
            zablokowane.append({**_wspolne(d), 'zablokowane': _iso(d.blocked_at), 'odrzucona': d.approved_at is None,
                                'to_samo_co': _to_samo_co(d, po_mac),
                                'proponowana_nazwa': _proponowana_nazwa(d, po_mac)})

    prosby.sort(key=lambda p: p['zgloszono'] or '', reverse=True)
    urzadzenia.sort(key=lambda u: (u['stanowisko_nazwa'], (u['nazwa'] or '').lower()))
    zablokowane.sort(key=lambda u: u['zablokowane'] or '', reverse=True)
    return {'prosby': prosby, 'urzadzenia': urzadzenia, 'zablokowane': zablokowane}


def zatwierdz(pk, nazwa, user_id):
    """
    Zatwierdza prośbę (albo odrzuconą wcześniej prośbę) i nadaje wiążącą nazwę. Zatwierdzone wpisy z tym samym MAC-iem
    (reinstalacja appki = nowe device_id) blokuje — jedno fizyczne urządzenie, jeden dostęp.
    """
    nazwa = _poprawna_nazwa(nazwa)
    device = _wiersz_do_zapisu(pk)
    odrzucona = device.status == ZABLOKOWANE and device.approved_at is None
    if device.status != OCZEKUJE and not odrzucona:
        raise _stan_zmieniony()

    zastapione = []
    if device.mac_address:
        inne = (ProductionDevice.query
                .filter(ProductionDevice.mac_address == device.mac_address,
                        ProductionDevice.id != device.id,
                        ProductionDevice.status == ZATWIERDZONE)
                .order_by(ProductionDevice.id).with_for_update().populate_existing().all())
        for stary in inne:
            ustaw_status(stary, ZABLOKOWANE, user_id)
            zastapione.append(stary.device_name or '(bez nazwy)')
            logger.info('Urządzenia: wpis zastąpiony przez reinstalację', extra={
                'event': 'device_replaced', 'stary_pk': stary.id, 'nowy_pk': device.id, 'user_id': user_id})

    device.device_name = nazwa
    ustaw_status(device, ZATWIERDZONE, user_id)
    db.session.flush()
    logger.info('Urządzenia: zatwierdzono', extra={
        'event': 'device_approved', 'device_pk': device.id, 'mac': device.mac_address, 'user_id': user_id})
    return {'zastapione': zastapione}


def odrzuc(pk, user_id):
    device = _wiersz_do_zapisu(pk)
    if device.status != OCZEKUJE:
        raise _stan_zmieniony()
    ustaw_status(device, ZABLOKOWANE, user_id)
    logger.info('Urządzenia: odrzucono prośbę', extra={
        'event': 'device_rejected', 'device_pk': device.id, 'mac': device.mac_address, 'user_id': user_id})


def zablokuj(pk, user_id):
    device = _wiersz_do_zapisu(pk)
    if device.status != ZATWIERDZONE:
        raise _stan_zmieniony()
    ustaw_status(device, ZABLOKOWANE, user_id)
    logger.info('Urządzenia: zablokowano', extra={'event': 'device_blocked', 'device_pk': device.id, 'user_id': user_id})


def odblokuj(pk, user_id):
    """Tylko urządzenie zatwierdzone kiedyś — odrzuconą prośbę zatwierdza się `zatwierdz` (z nadaniem nazwy)."""
    device = _wiersz_do_zapisu(pk)
    if device.status != ZABLOKOWANE or device.approved_at is None:
        raise _stan_zmieniony()
    ustaw_status(device, ZATWIERDZONE, user_id)
    logger.info('Urządzenia: odblokowano', extra={'event': 'device_unblocked', 'device_pk': device.id, 'user_id': user_id})


def zmien_nazwe(pk, nazwa):
    nazwa = _poprawna_nazwa(nazwa)
    device = _wiersz_do_zapisu(pk)
    if device.status != ZATWIERDZONE:
        raise _stan_zmieniony()
    device.device_name = nazwa


def przyjmij_mac(pk):
    device = _wiersz_do_zapisu(pk)
    if device.mac_conflict is None:
        raise _stan_zmieniony()
    logger.info('Urządzenia: przyjęto nowy MAC', extra={
        'event': 'device_mac_accepted', 'device_pk': device.id, 'stary': device.mac_address, 'nowy': device.mac_conflict})
    device.mac_address = device.mac_conflict
    device.mac_conflict = None


def podglad_bez_mac():
    wiersze = (ProductionDevice.query
               .filter(ProductionDevice.status == ZATWIERDZONE, ProductionDevice.mac_address.is_(None))
               .order_by(ProductionDevice.id).all())
    return {'urzadzenia': [{**_wspolne(d), 'ostatnio': _ostatnio(d)} for d in wiersze]}


def zablokuj_bez_mac(ids, user_id):
    """Blokuje wskazane w podglądzie, które WCIĄŻ są zatwierdzone i bez MAC-u; resztę zwraca jako pominięte."""
    ids = sorted({i for i in ids if isinstance(i, int) and not isinstance(i, bool)})
    wiersze = (ProductionDevice.query.filter(ProductionDevice.id.in_(ids))
               .order_by(ProductionDevice.id).with_for_update().populate_existing().all()) if ids else []
    znalezione = {d.id for d in wiersze}
    zablokowane, pominiete = [], [i for i in ids if i not in znalezione]
    for d in wiersze:
        if d.status == ZATWIERDZONE and d.mac_address is None:
            ustaw_status(d, ZABLOKOWANE, user_id)
            zablokowane.append(d.id)
        else:
            pominiete.append(d.id)
    logger.info('Urządzenia: blokada urządzeń bez MAC', extra={
        'event': 'device_block_without_mac', 'zablokowane': zablokowane, 'pominiete': pominiete, 'user_id': user_id})
    return {'zablokowane': zablokowane, 'pominiete': sorted(pominiete)}


def wydania_z_liczbami():
    """Wydania APK (jak w dawnych Ustawieniach) + liczba zatwierdzonych urządzeń z tym `version_code`."""
    from sqlalchemy import func
    from modules.production.services.mobile_api_service import list_releases
    liczby = dict(db.session.query(ProductionDevice.last_app_version_code, func.count(ProductionDevice.id))
                  .filter(ProductionDevice.status == ZATWIERDZONE)
                  .group_by(ProductionDevice.last_app_version_code).all())
    wydania = list_releases()
    for w in wydania:
        w['urzadzen'] = liczby.get(w['version_code'], 0)
    return wydania
