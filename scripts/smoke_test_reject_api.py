"""
Smoke test endpointu POST /api/mobile/orders/<id>/reject.
Wymaga uruchomionej lokalnie aplikacji (flask run) na :5000.

Wymaga też istniejącego device token. Skrypt pobiera token z bazy
(pierwszy ProductionDevice z station_code='formatting').

Uruchomienie:
  Terminal 1: venv/bin/python -m flask run --host=127.0.0.1 --port=5000
  Terminal 2: python3 scripts/smoke_test_reject_api.py
"""
import os
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import requests

BASE = os.environ.get('REJECT_API_BASE', 'http://127.0.0.1:5000')


def get_token():
    from app import create_app
    from modules.production.models import ProductionDevice
    app = create_app()
    with app.app_context():
        device = ProductionDevice.query.filter_by(station_code='formatting').first()
        if device is None:
            print("Brak zarejestrowanego device formatting - zarejestruj przez POST /api/mobile/register.")
            sys.exit(1)
        return device.token, device.device_id


def get_test_product_id():
    from app import create_app
    from modules.production.models import ProductionProduct
    app = create_app()
    with app.app_context():
        # Bierzemy pierwszy produkt w statusie czeka_na_formatowanie z quantity >= 1
        p = ProductionProduct.query.filter(
            ProductionProduct.current_status == 'czeka_na_formatowanie',
            ProductionProduct.quantity >= 1,
            ProductionProduct.original_product_id.is_(None),  # tylko oryginal
        ).first()
        if p is None:
            print("Brak produktu w czeka_na_formatowanie do testu.")
            sys.exit(1)
        return p.id, p.short_product_id, p.quantity, p.quantity_done_formatting


def main():
    token, device_id = get_token()
    product_id, short_id, qty, done = get_test_product_id()

    print(f"Test produkt: id={product_id}, short={short_id}, qty={qty}, sformatowane={done}")
    print(f"Cofamy 1 sztuke...")

    r = requests.post(
        f"{BASE}/api/mobile/orders/{product_id}/reject",
        headers={'Authorization': f'Bearer {token}'},
        json={
            'quantity': 1,
            'reason_category': 'wymiary',
            'station_code': 'formatting',
        },
        timeout=10,
    )

    print(f"Status: {r.status_code}")
    print(f"Response keys: {list(r.json().keys())}")
    assert r.status_code == 200, f"oczekiwano 200, dostalem {r.status_code}: {r.text}"

    data = r.json()
    assert 'original' in data and 'rework' in data and 'rework_log_id' in data
    assert data['rework']['is_rework'] is True
    assert data['rework']['original_product_id'] == product_id
    assert data['original']['quantity'] == qty - 1

    print("OK API endpoint reject (id={}, rework_log_id={})".format(product_id, data['rework_log_id']))


if __name__ == '__main__':
    main()
