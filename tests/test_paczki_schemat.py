# -*- coding: utf-8 -*-
"""Schemat paczek (logistyka etap 4, krok 4.2, spec 5.1–5.3 i 5.5)."""
import os
from datetime import datetime

from extensions import db
from migrations.migration_service import MigrationService
from modules.production.logistics import sposoby
from modules.production.logistics.models import AKCJE_LOGU, LogisticsLog
from modules.production.logistics.services import delivery
from modules.production.models import LabelPrintJob, ProductionPackage
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-09-30-logistyka-paczki.sql')


def _paczka(order, seq=1, kind='paczka', **kolumny):
    p = ProductionPackage(order_id=order.id, seq=seq, kind=kind,
                          declared_at=datetime(2026, 9, 30, 12, 0), **kolumny)
    db.session.add(p)
    db.session.commit()
    return p


def _polecenia():
    with open(MIGRACJA, encoding='utf-8') as f:
        sql = f.read()
    return sql, [' '.join(p.split()) for p in MigrationService.split_statements(sql)]


def test_paczka_ma_kod_i_stan_poczatkowy(app):
    order = zamowienie(statusy=('spakowane',))
    p = _paczka(order)
    assert p.kod == 'P-%d' % p.id
    assert (p.label_print_count, p.voided_at, p.label_delivery_text) == (0, None, None)
    assert p.order.id == order.id


def test_paleta_niestandardowa(app):
    p = _paczka(zamowienie(statusy=('spakowane',)), kind='paleta',
                pallet_type='niestandardowa', length_cm=150, width_cm=100)
    assert (p.kind, p.pallet_type, p.length_cm, p.width_cm) == ('paleta', 'niestandardowa', 150, 100)


def test_zamowienie_bez_deklaracji(app):
    assert zamowienie().packages_declared_at is None


def test_zadanie_wydruku_wskazuje_paczke(app):
    p = _paczka(zamowienie(statusy=('spakowane',)))
    job = LabelPrintJob(printer='wysylka', package_id=p.id, short_product_id=p.kod,
                        zpl_payload='^XA^XZ', station_code='packaging',
                        requested_by_type='device', requested_by_id='TAB-1')
    db.session.add(job)
    db.session.commit()
    assert LabelPrintJob.query.get(job.id).package_id == p.id


def test_log_logistyki_z_pracownikiem_i_urzadzeniem(app):
    order = zamowienie(statusy=('spakowane',))
    delivery.zapisz_log(order, 'paczki', None, u'3 × paczka', worker_id=5, device_id=7)
    db.session.commit()
    wpis = LogisticsLog.query.filter_by(order_id=order.id).one()
    assert (wpis.action, wpis.new_value, wpis.worker_id, wpis.device_id, wpis.user_id) == \
        ('paczki', u'3 × paczka', 5, 7, None)


def test_stale_wagi():
    assert sposoby.WAGA_KG_NA_M3 == 800 and sposoby.PROG_PALETY_KG == 40


def test_fikstura_numeru_wewnetrznego(app):
    """Endpointy paczek mają numer w ścieżce — na produkcji to same cyfry (bez '/')."""
    assert zamowienie(numer_wewnetrzny='1450').internal_order_number == '1450'


def test_migracja_paczek():
    sql, polecenia = _polecenia()
    tabela = next(p for p in polecenia if p.startswith('CREATE TABLE IF NOT EXISTS prod_packages'))
    for kolumna in ('seq SMALLINT NOT NULL', "kind ENUM('paczka','paleta') NOT NULL",
                    "pallet_type ENUM('eur','niestandardowa') NULL", 'declared_at DATETIME NOT NULL',
                    'voided_at DATETIME NULL', 'label_print_count INT NOT NULL DEFAULT 0',
                    'label_delivery_text VARCHAR(40) NULL', "verified_method ENUM('skan','reczne') NULL",
                    "loaded_method ENUM('skan','reczne') NULL", 'loaded_route_id INT NULL',
                    'KEY ix_prod_packages_order_id (order_id)', 'KEY ix_prod_packages_voided_at (voided_at)'):
        assert kolumna in tabela, kolumna
    assert 'REFERENCES prod_orders (id) ON DELETE CASCADE' in tabela
    enum = next(p for p in polecenia if p.startswith('ALTER TABLE prod_logistics_log MODIFY action'))
    # Akcje z kroków 4.3 i 4.4 dopisują migracje 2026-09-30-logistyka-weryfikacja.sql
    # i 2026-10-01-logistyka-dostawa.sql — ta migracja zna tylko akcje do kroku 4.2.
    akcje_po_4_2 = ('weryfikacja', 'weryfikacja_cofnieta', 'problem', 'problem_rozwiazany',
                    'cofniete_do_pakowania', 'zaladunek', 'zostaje', 'wyjazd', 'dostarczone',
                    'niedostarczone', 'dostarczenie_cofniete', 'niedostarczenie_cofniete')
    for akcja in AKCJE_LOGU:
        if akcja not in akcje_po_4_2:
            assert "'%s'" % akcja in enum, akcja
    assert 'paczki' in AKCJE_LOGU
    # 3 kolumny + klucz obcy — każdy ALTER dodający coś osłonięty warunkiem (runner wykonuje
    # katalog przy każdym deployu); MODIFY enuma jest idempotentny sam z siebie.
    assert sql.count('FROM information_schema.') == 4
    assert sql.count('PREPARE krok FROM @sql') == 4
    assert "CONSTRAINT_NAME = 'fk_prod_print_queue_package'" in sql
    assert 'REFERENCES prod_packages (id) ON DELETE SET NULL' in sql
    assert 'DELIMITER' not in sql.upper()


def test_runner_rozpoznaje_migracje():
    assert MigrationService(db=None)._match(os.path.basename(MIGRACJA)) is not None
    assert os.path.basename(MIGRACJA) > '2026-09-30-druk-klucze-przesuniecia.sql'
