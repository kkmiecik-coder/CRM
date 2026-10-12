"""Testy pobierania zamówień Baselinker po numerze (modal synchronizacji produkcji)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.routers.api.sync_api import parse_order_ids, MAX_ORDER_IDS_PER_FETCH
from modules.production.services.sync_service import BaselinkerSyncService, SyncError


def test_pusty_input_to_tryb_po_datach():
    assert parse_order_ids(None) == []
    assert parse_order_ids('') == []
    assert parse_order_ids([]) == []


def test_tekst_z_przecinkami_spacjami_i_duplikatami():
    assert parse_order_ids('48934086, 48934087;48934086\n48934088') == [48934086, 48934087, 48934088]


def test_lista_liczb_i_stringow():
    assert parse_order_ids([48934086, '48934087']) == [48934086, 48934087]


def test_nieprawidlowy_numer():
    with pytest.raises(ValueError, match='abc'):
        parse_order_ids('48934086, abc')


def test_limit_numerow():
    with pytest.raises(ValueError):
        parse_order_ids(list(range(1, MAX_ORDER_IDS_PER_FETCH + 2)))


def _serwis(odpowiedzi):
    """Serwis bez __init__ (bez configu aplikacji) z podmienionym requestem do API."""
    serwis = BaselinkerSyncService.__new__(BaselinkerSyncService)
    serwis.api_key = 'test'
    wywolania = []

    def fake_request(request_data):
        params = json.loads(request_data['parameters'])
        wywolania.append(params)
        return odpowiedzi[params['order_id']]

    serwis._make_api_request = fake_request
    return serwis, wywolania


def test_fetch_orders_by_ids_znalezione_i_brakujace():
    serwis, wywolania = _serwis({
        48934086: {'status': 'SUCCESS', 'orders': [{'order_id': 48934086, 'products': []}]},
        11111111: {'status': 'SUCCESS', 'orders': []},
    })

    znalezione, brakujace = serwis.fetch_orders_by_ids([48934086, 11111111])

    assert [o['order_id'] for o in znalezione] == [48934086]
    assert brakujace == [11111111]
    # Niepotwierdzone też, bez filtra statusów
    assert all(p['get_unconfirmed_orders'] is True for p in wywolania)
    assert all('filter_order_status_id' not in p for p in wywolania)


def test_fetch_orders_by_ids_blad_api():
    serwis, _ = _serwis({
        48934086: {'status': 'ERROR', 'error_message': 'Invalid token'},
    })

    with pytest.raises(SyncError, match='Invalid token'):
        serwis.fetch_orders_by_ids([48934086])
