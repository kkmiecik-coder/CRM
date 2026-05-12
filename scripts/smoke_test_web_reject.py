"""
Smoke test web endpointu POST /api/products/<id>/reject (bez auth, jak tablet używa).

Uruchomienie:
  Terminal 1: venv/bin/python -m flask run --host=127.0.0.1 --port=5000
  Terminal 2: python3 scripts/smoke_test_web_reject.py
"""
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import requests

BASE = 'http://127.0.0.1:5000'


def main():
    from app import create_app
    from modules.production.models import ProductionProduct
    app = create_app()

    with app.app_context():
        p = ProductionProduct.query.filter(
            ProductionProduct.current_status == 'czeka_na_formatowanie',
            ProductionProduct.quantity >= 1,
            ProductionProduct.original_product_id.is_(None),
        ).first()
        if p is None:
            print('Brak produktu w czeka_na_formatowanie')
            sys.exit(1)
        pid, qty, done = p.id, p.quantity, p.quantity_done_formatting or 0
        short = p.short_product_id

    print(f'Test produkt: id={pid}, short={short}, qty={qty}, done={done}')

    # Sprawdź najpierw URL — może mieć inny prefix
    url = f'{BASE}/production/api/products/{pid}/reject'
    print(f'POST {url}')

    r = requests.post(url, json={
        'quantity': 1,
        'reason_category': 'wymiary',
        'station_code': 'formatting',
    }, timeout=10)

    print(f'Status: {r.status_code}')
    print(f'Response: {r.json()}')
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get('success') is True
    assert data['rework']['is_rework'] is True
    print('OK web reject endpoint')


if __name__ == '__main__':
    main()
