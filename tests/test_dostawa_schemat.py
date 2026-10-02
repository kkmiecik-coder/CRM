# -*- coding: utf-8 -*-
"""Schemat kroku 4.4 (logistyka etap 4, spec 5.4, 5.5 i 9.1): statusy tras załadowana i w trasie, kolumny
załadunku, wyjazdu, dostarczenia i „Zostaje”, akcje logu Dostawy, status Base. „Załadowane”, stanowisko Dostawa
i znacznik kierowcy w katalogu pracowników."""
import os
import re
from datetime import date, datetime

from extensions import db
from migrations.migration_service import MigrationService
from modules.production.logistics import sposoby
from modules.production.logistics.models import (
    AKCJE_LOGU, STATUSY_TRASY, STATUSY_TRASY_AKTYWNE, Route, RouteStop,
)
from modules.production.models import ProductionDevice
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import _STATION_CODES_WITH_TABLETS, generate_token
from modules.production.services.station_catalog import STATION_LABELS, STATION_ORDER
from tests.logistyka_fixtures import app, client, kierowca, pracownik, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-10-01-logistyka-dostawa.sql')
AKCJE_DO_4_3 = ['sposob_dostawy', 'wydane', 'przepakowanie', 'trasa_dodane', 'trasa_usuniete', 'trasa_status',
                'adres', 'paczki', 'weryfikacja', 'weryfikacja_cofnieta', 'problem', 'problem_rozwiazany',
                'cofniete_do_pakowania']
AKCJE_DOSTAWY = ['zaladunek', 'zostaje', 'wyjazd', 'dostarczone', 'niedostarczone', 'dostarczenie_cofniete']


def _polecenia():
    with open(MIGRACJA, encoding='utf-8') as f:
        sql = f.read()
    return sql, [' '.join(p.split()) for p in MigrationService.split_statements(sql)]


def _wartosci(polecenie):
    return re.findall(r"'([a-z_]+)'", polecenie.split('ENUM(', 1)[1].split(')', 1)[0])


def test_statusy_tras_nowe_na_koncu_i_aktywne():
    assert STATUSY_TRASY == ('robocza', 'zatwierdzona', 'wykonana', 'zaladowana', 'w_trasie')
    assert STATUSY_TRASY_AKTYWNE == ('robocza', 'zatwierdzona', 'zaladowana', 'w_trasie')
    assert list(Route.status.type.enums) == list(STATUSY_TRASY)


def test_akcje_logu_dostawy_na_koncu():
    # U10 (Ruling 32) dopisuje za nimi `niedostarczenie_cofniete` — własną migracją (test_dostawa_niedostarczone_schemat).
    assert list(AKCJE_LOGU)[:len(AKCJE_DO_4_3 + AKCJE_DOSTAWY)] == AKCJE_DO_4_3 + AKCJE_DOSTAWY


def test_statusy_base_dostawy():
    assert sposoby.STATUS_ZALADOWANE == 524520
    assert (sposoby.STATUS_PLANOWANA_TRASA, sposoby.STATUS_WYSLANE_TRANSPORT,
            sposoby.STATUS_DOSTARCZONE_TRANSPORT) == (417343, 149763, 149778)


def test_kolumny_trasy_i_przystanku(app):
    chwila = datetime(2026, 10, 2, 7, 30)
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 2), date_to=date(2026, 10, 2), status='w_trasie',
                  loaded_at=chwila, loaded_by_worker_id=3, departed_at=chwila, departed_by_worker_id=4)
    db.session.add(trasa)
    db.session.flush()
    order = zamowienie()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1, delivered_at=chwila,
                             delivered_by_worker_id=5, stays_reason='brak_miejsca', stays_note=u'za długie'))
    db.session.commit()
    db.session.expire_all()
    t = Route.query.get(trasa.id)
    s = t.stops[0]
    assert (t.status, t.loaded_at, t.loaded_by_worker_id, t.departed_at, t.departed_by_worker_id) == \
        ('w_trasie', chwila, 3, chwila, 4)
    assert (s.delivered_at, s.delivered_by_worker_id, s.stays_reason, s.stays_note) == \
        (chwila, 5, 'brak_miejsca', u'za długie')


def test_migracja():
    sql, polecenia = _polecenia()
    trasy = next(p for p in polecenia if p.startswith('ALTER TABLE prod_routes MODIFY COLUMN status'))
    assert _wartosci(trasy) == list(STATUSY_TRASY)
    assert 'COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT' in trasy
    log = next(p for p in polecenia if p.startswith('ALTER TABLE prod_logistics_log MODIFY action'))
    # Pełna lista z chwili tej migracji (brakująca wartość skasowałaby akcję wpisom w logu); późniejsze dopisuje
    # migracja U10.
    assert _wartosci(log) == AKCJE_DO_4_3 + AKCJE_DOSTAWY
    for tabela, kolumna in (('prod_routes', 'loaded_at DATETIME NULL'),
                            ('prod_routes', 'loaded_by_worker_id INT NULL'),
                            ('prod_routes', 'departed_at DATETIME NULL'),
                            ('prod_routes', 'departed_by_worker_id INT NULL'),
                            ('prod_route_stops', 'delivered_at DATETIME NULL'),
                            ('prod_route_stops', 'delivered_by_worker_id INT NULL'),
                            ('prod_route_stops', 'stays_reason VARCHAR(32) NULL'),
                            ('prod_route_stops', 'stays_note VARCHAR(255) NULL')):
        assert 'ALTER TABLE %s ADD COLUMN %s' % (tabela, kolumna) in sql, kolumna
    assert sql.count('FROM information_schema.COLUMNS') == 8
    assert sql.count('PREPARE krok FROM @sql') == 8
    assert 'DELIMITER' not in sql.upper()


def test_stanowisko_dostawy_w_katalogu():
    assert 'delivery' in ProductionDevice.VALID_STATION_CODES
    assert STATION_LABELS['delivery'] == 'Dostawa'
    assert 'delivery' not in STATION_ORDER
    assert 'delivery' in _STATION_CODES_WITH_TABLETS


def test_rejestracja_telefonu_dostawy(app, client):
    r = client.post('/api/mobile/register', json={'device_id': 'TEL-KIEROWCA-1', 'device_name': 'Telefon kierowcy',
                                                  'station_code': 'delivery'})
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['station_code'] == 'delivery'


def test_katalog_pracownikow_ma_znacznik_kierowcy_i_nowy_ksztalt(app, client):
    k, p = kierowca(), pracownik()
    device = ProductionDevice(device_id='TEL-DOSTAWA-KAT', device_name='Telefon', station_code='delivery')
    db.session.add(device)
    db.session.commit()
    r = client.get('/api/mobile/workers', headers={'Authorization': 'Bearer ' + generate_token(device)})
    assert r.status_code == 200, r.get_data()[:300]
    profile = {w['id']: w for w in r.get_json()['workers']}
    assert profile[k.id]['is_driver'] is True and profile[p.id]['is_driver'] is False
    assert mobile_api.KSZTALT_KATALOGU_PRACOWNIKOW == 2
    # Nowe pole nie zmienia danych, z których liczy się ETag. Bez segmentu kształtu telefon z zapamiętanym
    # katalogiem dostawałby 304 i nie zobaczyłby is_driver (bramka Dostawy pokazuje tylko kierowców).
    assert r.headers['ETag'].startswith('W/"workers:2:')
