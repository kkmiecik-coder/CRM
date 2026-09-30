# -*- coding: utf-8 -*-
"""Schemat kroku 4.3 (logistyka etap 4, spec 4.1, 5.3 i 5.5): statusy po spakowaniu, kolumny
weryfikacji, problemu i banera przepakowania, akcje logu Weryfikacji, indeks paczek."""
import os
import re
from datetime import datetime

from migrations.migration_service import MigrationService
from modules.production.logistics import sposoby
from modules.production.logistics.models import AKCJE_LOGU
from modules.production.models import ProductionOrder, ProductionPackage, ProductionProduct
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-09-30-logistyka-weryfikacja.sql')
STARE_STATUSY = ['czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie',
                 'czeka_na_formatowanie', 'czeka_na_krawedzie', 'czeka_na_lakiernie',
                 'czeka_na_logistyke', 'czeka_na_pakowanie', 'spakowane', 'anulowane',
                 'wstrzymane', 'w_realizacji']
STARE_AKCJE = ['sposob_dostawy', 'wydane', 'przepakowanie', 'trasa_dodane', 'trasa_usuniete',
               'trasa_status', 'adres', 'paczki']


def _polecenia():
    with open(MIGRACJA, encoding='utf-8') as f:
        sql = f.read()
    return sql, [' '.join(p.split()) for p in MigrationService.split_statements(sql)]


def _wartosci(polecenie):
    return re.findall(r"'([a-z_]+)'", polecenie.split('ENUM(', 1)[1].split(')', 1)[0])


def test_stale_statusow():
    assert sposoby.STATUSY_PO_SPAKOWANIU == ('spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone')
    assert sposoby.STATUSY_LOGISTYCZNE == ('zweryfikowane', 'zaladowane', 'dostarczone')
    assert sposoby.PRZEPAKUJ_NA_KURIERA == u'Przepakuj na kuriera'


def test_nowe_statusy_na_koncu_enuma():
    """Dopisanie NA KOŃCU: MySQL 8 zmienia same metadane, a stare wartości zachowują porządek."""
    wartosci = list(ProductionProduct.current_status.type.enums)
    assert wartosci == STARE_STATUSY + ['zweryfikowane', 'zaladowane', 'dostarczone']


def test_nazwy_nowych_statusow(app):
    order = zamowienie(statusy=('zweryfikowane', 'zaladowane', 'dostarczone'))
    assert [p.status_display_name for p in order.products] == ['Zweryfikowane', u'Załadowane', 'Dostarczone']


def test_kolumny_weryfikacji_i_problemu_na_zamowieniu(app):
    chwila = datetime(2026, 10, 1, 9, 30)
    order = zamowienie(statusy=('spakowane',), verified_at=chwila, verified_by_worker_id=3,
                       problem_reason='etykieta', problem_note=u'nieczytelna', problem_at=chwila,
                       problem_by_worker_id=4, repack_reason=u'Weryfikacja: Etykieta')
    o = ProductionOrder.query.get(order.id)
    assert (o.verified_at, o.verified_by_worker_id, o.problem_reason, o.problem_note, o.problem_at,
            o.problem_by_worker_id, o.repack_reason) == \
        (chwila, 3, 'etykieta', u'nieczytelna', chwila, 4, u'Weryfikacja: Etykieta')
    pusty = zamowienie()
    assert (pusty.verified_at, pusty.problem_at, pusty.repack_reason) == (None, None, None)


def test_akcje_logu_weryfikacji():
    assert list(AKCJE_LOGU) == STARE_AKCJE + ['weryfikacja', 'weryfikacja_cofnieta', 'problem',
                                              'problem_rozwiazany', 'cofniete_do_pakowania']


def test_indeks_paczek_po_zamowieniu_i_uniewaznieniu():
    indeksy = {i.name: [c.name for c in i.columns] for i in ProductionPackage.__table__.indexes}
    assert indeksy['ix_prod_packages_order_voided'] == ['order_id', 'voided_at']
    assert 'ix_prod_packages_voided_at' not in indeksy
    assert indeksy['ix_prod_packages_order_id'] == ['order_id']


def test_migracja():
    sql, polecenia = _polecenia()
    status = next(p for p in polecenia
                  if p.startswith('ALTER TABLE prod_products MODIFY COLUMN current_status'))
    assert _wartosci(status) == list(ProductionProduct.current_status.type.enums)
    assert 'COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT' in status
    log = next(p for p in polecenia if p.startswith('ALTER TABLE prod_logistics_log MODIFY action'))
    assert _wartosci(log) == list(AKCJE_LOGU)
    for kolumna in ('verified_at DATETIME NULL', 'verified_by_worker_id INT NULL',
                    'problem_reason VARCHAR(32) NULL', 'problem_note VARCHAR(255) NULL',
                    'problem_at DATETIME NULL', 'problem_by_worker_id INT NULL',
                    'repack_reason VARCHAR(255) NULL'):
        assert 'ALTER TABLE prod_orders ADD COLUMN %s' % kolumna in sql, kolumna
    # 7 kolumn + nowy indeks + zdjęcie starego — każdy osłonięty warunkiem.
    assert sql.count('FROM information_schema.COLUMNS') == 7
    assert sql.count('FROM information_schema.STATISTICS') == 2
    assert sql.count('PREPARE krok FROM @sql') == 9
    assert 'ALTER TABLE prod_packages ADD INDEX ix_prod_packages_order_voided (order_id, voided_at)' in sql
    assert 'ALTER TABLE prod_packages DROP INDEX ix_prod_packages_voided_at' in sql
    od = next(p for p in polecenia if p.startswith('INSERT IGNORE INTO prod_config'))
    assert "'logistyka_weryfikacja_od'" in od and 'CAST(NOW() AS CHAR)' in od
    # Wydane odbiory przestawia cron po restarcie (delivery.dostarcz_wydane): migracja działa PRZED
    # restartem, a stary kod nie zna 'dostarczone' w ENUM — żadnego UPDATE pozycji w tym pliku.
    assert 'UPDATE prod_products' not in sql
    assert not any(p.upper().startswith('UPDATE') for p in polecenia)
    assert 'DELIMITER' not in sql.upper()


def test_runner_rozpoznaje_migracje():
    nazwa = os.path.basename(MIGRACJA)
    assert MigrationService(db=None)._match(nazwa) is not None
    assert nazwa > '2026-09-30-logistyka-paczki.sql'
