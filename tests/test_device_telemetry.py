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
