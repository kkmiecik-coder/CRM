# -*- coding: utf-8 -*-
"""Serializery trakowni — pracownik nie może zobaczyć deklaracji."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from modules.production.sawmill.services.serializers import (
    DEVICE_FORBIDDEN_FIELDS,
    serialize_log_for_device,
    serialize_order_for_device,
    serialize_order_for_panel,
)


def _order():
    """Atrapa zlecenia z KOMPLETEM pól, w tym wrażliwymi."""
    return SimpleNamespace(
        id=12,
        order_number='TRK/2026/007',
        status='in_progress',
        started_at=datetime(2026, 8, 5, 7, 12, 0),
        completed_at=None,
        declared_volume_m3=Decimal('80.000'),
        declared_logs_count=120,
        price_per_m3=Decimal('1200.00'),
        declared_value=Decimal('96000.00'),
        agreed_volume_m3=None,
        notes='UWAGA: wg WZ ma być 80 m3',
        settlement_notes=None,
        species_id=7,
        delivery_id=3,
        species=SimpleNamespace(name='Dąb'),
        delivery=SimpleNamespace(
            invoice_number='FV/2026/0451',
            invoice_date=date(2026, 8, 2),
            delivery_date=date(2026, 8, 3),
            supplier=SimpleNamespace(name='Tartak Nowak sp. z o.o.'),
        ),
    )


def test_tablet_dostaje_tylko_dozwolone_pola():
    out = serialize_order_for_device(_order(), 46, Decimal('23.847'))
    assert set(out.keys()) == {
        'id', 'order_number', 'species', 'supplier_name', 'invoice_number',
        'delivery_date', 'status', 'logs_count', 'measured_volume_m3', 'started_at',
    }


def test_zadne_wrazliwe_pole_nie_wycieka():
    """Główny test bezpieczeństwa całego modułu."""
    out = serialize_order_for_device(_order(), 46, Decimal('23.847'))
    for zakazane in DEVICE_FORBIDDEN_FIELDS:
        assert zakazane not in out, u'wyciek pola {}'.format(zakazane)


def test_notatka_nie_trafia_na_tablet():
    """Najbardziej prawdopodobne miejsce, gdzie ktoś wpisze deklarację."""
    out = serialize_order_for_device(_order(), 46, Decimal('23.847'))
    surowo = repr(out)
    assert 'WZ' not in surowo
    assert '80' not in surowo.replace('0451', '').replace('2026', '')


def test_tablet_widzi_sume_swoich_pomiarow():
    out = serialize_order_for_device(_order(), 46, Decimal('23.847'))
    assert out['logs_count'] == 46
    assert out['measured_volume_m3'] == 23.847


def test_serializacja_pomiaru():
    log = SimpleNamespace(
        id=501, sequence_no=46,
        mid_circumference_cm=Decimal('125.6'),
        length_cm=Decimal('410.0'), volume_m3=Decimal('0.514699'),
        measured_at=datetime(2026, 8, 5, 9, 31, 12),
    )
    out = serialize_log_for_device(log)
    assert out['volume_m3'] == 0.514699
    assert out['measured_at'] == '2026-08-05T09:31:12'
    assert out['sequence_no'] == 46


def test_panel_widzi_wszystko():
    differences = {
        'difference_m3': Decimal('-3.660'),
        'difference_pct': Decimal('-4.58'),
        'difference_value': Decimal('-4392.00'),
        'is_deviation': False,
    }
    out = serialize_order_for_panel(_order(), 46, Decimal('76.340'), differences)
    assert out['declared_volume_m3'] == 80.0
    assert out['price_per_m3'] == 1200.0
    assert out['difference_m3'] == -3.66
    assert out['is_deviation'] is False
    assert out['notes'] == 'UWAGA: wg WZ ma być 80 m3'
