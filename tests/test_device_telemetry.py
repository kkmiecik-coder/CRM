"""Testy telemetrii urządzeń produkcyjnych."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.services.mobile_api_service import validate_heartbeat_payload


def test_validate_heartbeat_ok():
    err = validate_heartbeat_payload({
        'battery_pct': 87,
        'battery_charging': True,
        'temperature_c': 32.5,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
        'ip_address': '192.168.33.7',
    })
    assert err is None


def test_validate_heartbeat_battery_out_of_range():
    err = validate_heartbeat_payload({
        'battery_pct': 150,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
    })
    assert err == 'battery_pct out of range'


def test_validate_heartbeat_battery_negative():
    err = validate_heartbeat_payload({
        'battery_pct': -1,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
    })
    assert err == 'battery_pct out of range'


def test_validate_heartbeat_battery_null_ok():
    err = validate_heartbeat_payload({
        'battery_pct': None,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
    })
    assert err is None


def test_validate_heartbeat_temperature_out_of_range():
    err = validate_heartbeat_payload({
        'temperature_c': 999,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
    })
    assert err == 'temperature_c out of range'


def test_validate_heartbeat_temperature_negative_extreme():
    err = validate_heartbeat_payload({
        'temperature_c': -50,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
    })
    assert err == 'temperature_c out of range'


def test_validate_heartbeat_missing_app_version_code():
    err = validate_heartbeat_payload({
        'app_version_name': '1.0.15',
    })
    assert err == 'app_version_code required'


def test_validate_heartbeat_missing_app_version_name():
    err = validate_heartbeat_payload({
        'app_version_code': 16,
    })
    assert err == 'app_version_name required'


from datetime import datetime, timedelta
from types import SimpleNamespace

from modules.production.services.mobile_api_service import build_devices_telemetry


def _make_device(station_code, **kw):
    """Lekki stub ProductionDevice — tylko atrybuty których używa helper."""
    defaults = dict(
        station_code=station_code,
        is_active=True,
        last_heartbeat_at=None,
        last_battery_pct=None,
        last_battery_charging=None,
        last_temperature_c=None,
        last_app_version_code=None,
        app_version=None,
        last_ip=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_telemetry_empty_fleet():
    """Brak urządzeń → wszystkie stanowiska Niedostępne."""
    result = build_devices_telemetry([], now=datetime(2026, 5, 21, 15, 0, 0))
    assert set(result.keys()) == {
        'cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging'
    }
    for code, status in result.items():
        assert status['active'] is False
        assert status['status_label'] == 'Niedostępne'
        assert status['last_heartbeat_at'] is None
        assert status['battery_pct'] is None
        assert status['apk_outdated'] is False


def test_telemetry_active_device():
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [_make_device(
        'cutting',
        last_heartbeat_at=now - timedelta(minutes=2),
        last_battery_pct=87,
        last_battery_charging=True,
        last_temperature_c=32.5,
        last_app_version_code=16,
        app_version='1.0.15',
        last_ip='192.168.33.7',
    )]
    result = build_devices_telemetry(devices, now=now)
    cutting = result['cutting']
    assert cutting['active'] is True
    assert cutting['status_label'] == 'Aktywne'
    assert cutting['battery_pct'] == 87
    assert cutting['battery_charging'] is True
    assert cutting['temperature_c'] == 32.5
    assert cutting['app_version_name'] == '1.0.15'
    assert cutting['app_version_code'] == 16
    assert cutting['ip_address'] == '192.168.33.7'
    assert cutting['apk_outdated'] is False


def test_telemetry_stale_device_inactive():
    """Heartbeat >20 min temu → status Niedostępne."""
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [_make_device(
        'cutting',
        last_heartbeat_at=now - timedelta(minutes=25),
        last_battery_pct=50,
        last_app_version_code=16,
        app_version='1.0.15',
    )]
    result = build_devices_telemetry(devices, now=now)
    assert result['cutting']['active'] is False
    assert result['cutting']['status_label'] == 'Niedostępne'


def test_telemetry_threshold_boundary_19m59s_active():
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [_make_device(
        'cutting',
        last_heartbeat_at=now - timedelta(minutes=19, seconds=59),
        last_app_version_code=16,
        app_version='1.0.15',
    )]
    assert build_devices_telemetry(devices, now=now)['cutting']['active'] is True


def test_telemetry_threshold_boundary_20m_inactive():
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [_make_device(
        'cutting',
        last_heartbeat_at=now - timedelta(minutes=20),
        last_app_version_code=16,
        app_version='1.0.15',
    )]
    assert build_devices_telemetry(devices, now=now)['cutting']['active'] is False


def test_telemetry_apk_outdated():
    """Tablet z niższym version_code niż max w flocie = outdated."""
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [
        _make_device('cutting',
            last_heartbeat_at=now - timedelta(minutes=2),
            last_app_version_code=16, app_version='1.0.15'),
        _make_device('assembly',
            last_heartbeat_at=now - timedelta(minutes=2),
            last_app_version_code=15, app_version='1.0.14'),
    ]
    result = build_devices_telemetry(devices, now=now)
    assert result['cutting']['apk_outdated'] is False
    assert result['assembly']['apk_outdated'] is True


def test_telemetry_multiple_devices_per_station_uses_freshest():
    """Gdy 2 tablety na stanowisku, używamy tego ze świeższym heartbeat."""
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [
        _make_device('cutting',
            last_heartbeat_at=now - timedelta(minutes=10),
            last_battery_pct=50,
            last_app_version_code=16, app_version='1.0.15'),
        _make_device('cutting',
            last_heartbeat_at=now - timedelta(minutes=2),
            last_battery_pct=90,
            last_app_version_code=16, app_version='1.0.15'),
    ]
    result = build_devices_telemetry(devices, now=now)
    assert result['cutting']['battery_pct'] == 90


def test_telemetry_inactive_device_excluded_from_fleet_max():
    """is_active=False urządzenia nie liczą się do max APK floty."""
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [
        _make_device('cutting',
            last_heartbeat_at=now - timedelta(minutes=2),
            last_app_version_code=16, app_version='1.0.15'),
        _make_device('assembly',
            is_active=False,
            last_heartbeat_at=now - timedelta(minutes=2),
            last_app_version_code=99, app_version='9.9.9'),
    ]
    result = build_devices_telemetry(devices, now=now)
    assert result['cutting']['apk_outdated'] is False
