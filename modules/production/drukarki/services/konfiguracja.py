# -*- coding: utf-8 -*-
"""Dokument konfiguracji agenta druku v2 z wersją, historią i dwukierunkowym zapisem (CRM albo agent).

Przy równoczesnych zapisach wygrywa ten, który serwer przetworzył później; nadpisana wersja
trafia do historii (`overwrote_version`). Przesunięcia lądują w prod_config pod kluczami, które czytają
generatory ZPL. Funkcje nie commitują."""
import ipaddress
import json
import re
from datetime import datetime

from extensions import db
from modules.production.drukarki import stale
from modules.production.drukarki.models import PrintAgentConfig, PrintAgentConfigChange
from modules.production.models import ProductionConfig
from modules.production.services import package_label
from modules.production.services.label_print_service import DEFAULT_CONFIG

KLUCZ_LT = 'LABEL_PRINTER_OFFSET_LT'
KLUCZ_LS = 'LABEL_PRINTER_OFFSET_LS'
# Dotychczasowy zapis LT/LS w panelu nie ma żadnego zakresu; etykieta 60×40 ma 480 punktów szerokości,
# więc przesunięcie poza nią to błąd, nie kalibracja.
MAKS_PRZESUNIECIA_ETYKIET = 480
ODCZYTY_STANU = ('snmp', 'brak')
_GODZINA = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def _int_z_bazy(klucz, domyslna):
    wiersz = ProductionConfig.query.filter_by(config_key=klucz).first()
    try:
        return int(str(wiersz.config_value).strip()) if wiersz is not None else domyslna
    except (TypeError, ValueError):
        return domyslna


def domyslna():
    dx, dy = package_label.wczytaj_przesuniecie()
    return {
        'drukarki': [],
        'przesuniecia': {
            'etykiety': {'lt': _int_z_bazy(KLUCZ_LT, DEFAULT_CONFIG['offset_lt']),
                         'ls': _int_z_bazy(KLUCZ_LS, DEFAULT_CONFIG['offset_ls'])},
            'wysylka': {'dx': dx, 'dy': dy},
        },
        'godziny': {'pn_pt': ['05:30', '15:30'], 'sobota': ['05:30', '15:30']},
    }


def _liczba(wartosc):
    return isinstance(wartosc, int) and not isinstance(wartosc, bool)


def waliduj(dane):
    """Lista błędów po polsku; pusta = dokument poprawny."""
    if not isinstance(dane, dict):
        return ['Konfiguracja musi być obiektem.']
    bledy = []
    widziane = set()
    drukarki = dane.get('drukarki')
    if not isinstance(drukarki, list):
        bledy.append('Pole „drukarki” musi być listą.')
        drukarki = []
    for d in drukarki:
        if not isinstance(d, dict):
            bledy.append('Wpis drukarki musi być obiektem.')
            continue
        nazwa = d.get('nazwa')
        if nazwa not in stale.ROLE:
            bledy.append('Nieznana nazwa drukarki: %s.' % nazwa)
            continue
        if nazwa in widziane:
            bledy.append('Drukarka „%s” występuje więcej niż raz.' % nazwa)
        widziane.add(nazwa)
        try:
            if not isinstance(d.get('ip'), str) or d['ip'].count('.') != 3:
                raise ValueError
            ipaddress.IPv4Address(d['ip'])
        except ValueError:
            bledy.append('Drukarka „%s”: niepoprawny adres IP.' % nazwa)
        port = d.get('port')
        if not _liczba(port) or not 1 <= port <= 65535:
            bledy.append('Drukarka „%s”: port musi być liczbą od 1 do 65535.' % nazwa)
        if d.get('odczyt_stanu') not in ODCZYTY_STANU:
            bledy.append('Drukarka „%s”: odczyt stanu to snmp albo brak.' % nazwa)
        limit = d.get('limit_wysylki_s')
        if not _liczba(limit) or limit < 1:
            bledy.append('Drukarka „%s”: limit wysyłki musi być dodatnią liczbą sekund.' % nazwa)
        if not isinstance(d.get('model'), str):
            bledy.append('Drukarka „%s”: model musi być tekstem.' % nazwa)

    prz = dane.get('przesuniecia')
    if not isinstance(prz, dict):
        bledy.append('Pole „przesunięcia” musi być obiektem.')
        prz = {}
    et = prz.get('etykiety') if isinstance(prz.get('etykiety'), dict) else {}
    wy = prz.get('wysylka') if isinstance(prz.get('wysylka'), dict) else {}
    for klucz in ('lt', 'ls'):
        w = et.get(klucz)
        if not _liczba(w) or abs(w) > MAKS_PRZESUNIECIA_ETYKIET:
            bledy.append('Przesunięcie etykiet %s musi być liczbą całkowitą w zakresie ±%d.'
                         % (klucz.upper(), MAKS_PRZESUNIECIA_ETYKIET))
    for klucz in ('dx', 'dy'):
        w = wy.get(klucz)
        if not _liczba(w) or abs(w) > package_label.MAKS_PRZESUNIECIA:
            bledy.append('Przesunięcie paczek %s musi być liczbą całkowitą w zakresie ±%d.'
                         % (klucz, package_label.MAKS_PRZESUNIECIA))

    godz = dane.get('godziny')
    if not isinstance(godz, dict):
        bledy.append('Pole „godziny” musi być obiektem.')
        godz = {}
    for klucz, opis in (('pn_pt', 'poniedziałek–piątek'), ('sobota', 'sobota')):
        para = godz.get(klucz)
        if (not isinstance(para, list) or len(para) != 2
                or not all(isinstance(x, str) and _GODZINA.match(x) for x in para)):
            bledy.append('Godziny pracy (%s) muszą mieć postać HH:MM – HH:MM.' % opis)
        elif para[0] >= para[1]:
            bledy.append('Godziny pracy (%s): początek musi być wcześniej niż koniec.' % opis)
    return bledy


def _zapisz_przesuniecia(dane):
    wartosci = {
        KLUCZ_LT: dane['przesuniecia']['etykiety']['lt'],
        KLUCZ_LS: dane['przesuniecia']['etykiety']['ls'],
        package_label.KLUCZ_PRZESUNIECIA_X: dane['przesuniecia']['wysylka']['dx'],
        package_label.KLUCZ_PRZESUNIECIA_Y: dane['przesuniecia']['wysylka']['dy'],
    }
    wiersze = {c.config_key: c for c in ProductionConfig.query.filter(
        ProductionConfig.config_key.in_(list(wartosci))).all()}
    for klucz, wartosc in wartosci.items():
        if klucz in wiersze:
            wiersze[klucz].config_value = str(wartosc)
        else:
            db.session.add(ProductionConfig(config_key=klucz, config_value=str(wartosc),
                                            config_type='integer',
                                            config_description='Przesunięcie wydruku (agent druku v2)'))


def zapisz(agent_id, dane, wersja_bazowa, zrodlo, aktor):
    """Zapisuje dokument jako nową wersję. Zwraca (wiersz konfiguracji, nadpisana wersja albo None).

    Wołający waliduje dane wcześniej i commituje. Wiersz konfiguracji jest blokowany (FOR UPDATE), więc
    równoległe zapisy idą po kolei; późniejszy po stronie serwera wygrywa."""
    wiersz = PrintAgentConfig.query.filter_by(agent_id=agent_id).with_for_update().first()
    if wiersz is None:
        raise ValueError('Agent nie ma konfiguracji.')
    obecna = wiersz.version
    nadpisana = obecna if wersja_bazowa is not None and wersja_bazowa < obecna else None
    przed = wiersz.data
    po = json.dumps(dane, ensure_ascii=False, sort_keys=True)
    wiersz.version = obecna + 1
    wiersz.data = po
    wiersz.updated_at = datetime.utcnow()
    wiersz.updated_source = zrodlo
    wiersz.updated_by = aktor
    db.session.add(PrintAgentConfigChange(
        agent_id=agent_id, version=wiersz.version, base_version=wersja_bazowa, source=zrodlo, actor=aktor,
        data_before=przed, data_after=po, overwrote_version=nadpisana, created_at=wiersz.updated_at))
    _zapisz_przesuniecia(dane)
    db.session.flush()
    return wiersz, nadpisana


def historia(agent_id, limit=50):
    wiersze = (PrintAgentConfigChange.query.filter_by(agent_id=agent_id)
               .order_by(PrintAgentConfigChange.id.desc()).limit(limit).all())
    return [{'wersja': c.version, 'wersja_bazowa': c.base_version, 'zrodlo': c.source, 'aktor': c.actor,
             'przed': json.loads(c.data_before) if c.data_before else None,
             'po': json.loads(c.data_after) if c.data_after else None,
             'nadpisana_wersja': c.overwrote_version,
             'czas': c.created_at.isoformat() if c.created_at else None} for c in wiersze]
