# -*- coding: utf-8 -*-
"""Model i migracja dostępu urządzeń (spec 2026-10-12, sekcja 3)."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.models import ProductionDevice
from tests.urzadzenia_fixtures import app  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRACJA = os.path.join(KORZEN, 'migrations', '2026-10-12-urzadzenia-zatwierdzanie.sql')
NOWE_KOLUMNY = ('status', 'mac_address', 'mac_conflict', 'device_model', 'requested_at',
                'approved_at', 'approved_by', 'blocked_at', 'blocked_by')


def test_stale_statusow():
    assert ProductionDevice.STATUS_OCZEKUJE == 'oczekuje'
    assert ProductionDevice.STATUS_ZATWIERDZONE == 'zatwierdzone'
    assert ProductionDevice.STATUS_ZABLOKOWANE == 'zablokowane'
    assert ProductionDevice.STATUSY == ('oczekuje', 'zatwierdzone', 'zablokowane')


def test_wiersz_bez_statusu_jest_zatwierdzony(app):
    """Domyślne 'zatwierdzone' = semantyka starego kodu (wiersz założony po wycofaniu backendu)."""
    d = ProductionDevice(device_id='TAB-DOMYSLNY', station_code='packaging')
    db.session.add(d)
    db.session.commit()
    assert d.status == 'zatwierdzone'
    assert d.is_active is True


def test_migracja_dodaje_kazda_nowa_kolumne():
    with open(MIGRACJA, encoding='utf-8') as f:
        tresc = f.read()
    for kolumna in NOWE_KOLUMNY:
        assert kolumna in ProductionDevice.__table__.columns, kolumna
        assert f"COLUMN_NAME = '{kolumna}'" in tresc, kolumna
        assert re.search(rf'ADD COLUMN {kolumna} ', tresc), kolumna
    assert "INDEX_NAME = 'ix_prod_devices_mac_address'" in tresc


def test_migracja_nie_rusza_tokenow():
    with open(MIGRACJA, encoding='utf-8') as f:
        tresc = f.read()
    assert 'token_version' not in tresc
