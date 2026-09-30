# -*- coding: utf-8 -*-
"""Kolejka wydruku zna drukarkę (logistyka etap 4, krok 4.1, spec 5.1)."""
import os

from modules.production.models import LabelPrintJob
from tests.druk_fixtures import app, zadanie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-09-30-druk-dwie-drukarki.sql')


def test_stale_drukarek():
    assert LabelPrintJob.DRUKARKA_ETYKIETY == 'etykiety'
    assert LabelPrintJob.DRUKARKA_WYSYLKA == 'wysylka'
    assert LabelPrintJob.DRUKARKI == ('etykiety', 'wysylka')


def test_zadanie_bez_drukarki_idzie_na_etykiety(app):
    """Dzisiejszy kod etykiet produktów nie podaje drukarki — musi trafić na starą."""
    job = zadanie()
    assert LabelPrintJob.query.get(job.id).printer == 'etykiety'
    assert job.package_id is None


def test_zadanie_na_drukarke_wysylki(app):
    job = zadanie(printer='wysylka', kod='P-1')
    assert LabelPrintJob.query.get(job.id).printer == 'wysylka'


def test_migracja_drukarek():
    sql = open(MIGRACJA, encoding='utf-8').read()
    assert "ADD COLUMN printer VARCHAR(20) NOT NULL DEFAULT ''etykiety''" in sql
    assert 'ADD COLUMN package_id INT NULL' in sql
    assert 'ADD INDEX ix_prod_print_queue_printer_status (printer, status)' in sql
    # każdy z trzech ALTER-ów osłonięty warunkiem (runner wykonuje katalog przy każdym deployu)
    assert sql.count('FROM information_schema.') == 3
    assert sql.count('PREPARE krok FROM @sql') == 3
    assert 'DELIMITER' not in sql
