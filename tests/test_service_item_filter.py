"""Testy ignorowania pozycji usługowych przy synchronizacji produkcji.

Pozycje typu "Docięcie do wymiaru - usługa cięcia blatów..." trafiają z
Allegro/BaseLinker jako osobny "produkt", choć są tylko dodatkowym kosztem usługi
i nie powinny trafiać do produkcji ani blokować walidacji zamówienia.
"""
import json
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.services.parser_service import is_non_production_item
from modules.production.services.sync_service import BaselinkerSyncService


# --- is_non_production_item -------------------------------------------------

def test_wykrywa_pelna_nazwe_aukcji_uslugi():
    nazwa = "Docięcie do wymiaru - usługa cięcia blatów, trepów i parapetów na wymiar"
    assert is_non_production_item(nazwa) is True


def test_wykrywa_warianty_slowa_usluga():
    for nazwa in ["usługa", "usługi", "usluga", "uslugi", "Usługa docięcia", "USŁUGA"]:
        assert is_non_production_item(nazwa) is True, nazwa


def test_zwykly_produkt_nie_jest_usluga():
    assert is_non_production_item("Blat dębowy 120x80x4 lity olejowany") is False


def test_pusta_lub_none_nazwa_nie_jest_usluga():
    assert is_non_production_item("") is False
    assert is_non_production_item(None) is False


# --- _split_production_items -------------------------------------------------

def _service():
    # __new__ omija __init__ (bez konfiguracji API / kontekstu Flaska)
    return BaselinkerSyncService.__new__(BaselinkerSyncService)


def test_split_oddziela_usluge_od_produktu():
    produkty = [
        {'name': 'Blat dębowy 120x80x4', 'quantity': 1},
        {'name': 'Docięcie do wymiaru - usługa cięcia', 'quantity': 1},
    ]
    production, ignored = _service()._split_production_items(produkty)
    assert [p['name'] for p in production] == ['Blat dębowy 120x80x4']
    assert [p['name'] for p in ignored] == ['Docięcie do wymiaru - usługa cięcia']


def test_split_zamowienie_tylko_uslugowe():
    produkty = [{'name': 'usługa cięcia', 'quantity': 2}]
    production, ignored = _service()._split_production_items(produkty)
    assert production == []
    assert len(ignored) == 1


def test_split_pusta_lista():
    production, ignored = _service()._split_production_items([])
    assert production == []
    assert ignored == []


def test_split_zachowuje_obiekty_i_kolejnosc():
    a = {'name': 'Blat A', 'quantity': 1}
    b = {'name': 'Blat B', 'quantity': 1}
    production, ignored = _service()._split_production_items([a, b])
    assert production == [a, b]
    assert ignored == []


def test_split_ignoruje_usluge_bez_wymiarow():
    produkty = [{'name': 'Docięcie do wymiaru - usługa cięcia blatów na wymiar', 'quantity': 1}]
    production, ignored = _service()._split_production_items(produkty)
    assert production == []
    assert len(ignored) == 1


def test_split_nie_ignoruje_pozycji_z_usluga_ale_z_wymiarami():
    # Realny produkt z "usługą" w nazwie, ale Z WYMIARAMI → musi trafić do produkcji
    produkty = [{'name': 'Blat dębowy 120x80x4 lity + usługa olejowania', 'quantity': 1}]
    production, ignored = _service()._split_production_items(produkty)
    assert [p['name'] for p in production] == ['Blat dębowy 120x80x4 lity + usługa olejowania']
    assert ignored == []


# --- _upsert_system_order_comment (wspólny helper komentarza) ----------------

def _service_with_api():
    svc = BaselinkerSyncService.__new__(BaselinkerSyncService)
    svc.api_key = 'test-token'
    svc._make_api_request = MagicMock(return_value={'status': 'SUCCESS'})
    return svc


def _sent_admin_comment(svc):
    request_data = svc._make_api_request.call_args[0][0]
    return json.loads(request_data['parameters'])['admin_comments']


def test_upsert_wysyla_nowy_komentarz_gdy_brak_istniejacego():
    svc = _service_with_api()
    ok = svc._upsert_system_order_comment(123, "SYSTEM: Test", "SYSTEM: Test", "")
    assert ok is True
    assert _sent_admin_comment(svc) == "SYSTEM: Test"


def test_upsert_laczy_z_istniejacym_komentarzem():
    svc = _service_with_api()
    svc._upsert_system_order_comment(1, "SYSTEM: Nowy", "SYSTEM: Nowy", "Uwaga klienta")
    assert _sent_admin_comment(svc) == "Uwaga klienta | SYSTEM: Nowy"


def test_upsert_dedup_nie_wysyla_gdy_marker_obecny():
    svc = _service_with_api()
    ok = svc._upsert_system_order_comment(1, "SYSTEM: Nowy", "SYSTEM: Nowy", "wcześniej | SYSTEM: Nowy szczegóły")
    assert ok is True
    svc._make_api_request.assert_not_called()


def test_upsert_obcina_do_200_znakow():
    svc = _service_with_api()
    svc._upsert_system_order_comment(1, "SYSTEM: Y", "SYSTEM: Y", "x" * 250)
    sent = _sent_admin_comment(svc)
    assert len(sent) == 200
    assert sent.endswith("...")


def test_upsert_zwraca_false_bez_api_key():
    svc = BaselinkerSyncService.__new__(BaselinkerSyncService)
    svc.api_key = None
    assert svc._upsert_system_order_comment(1, "m", "m", "") is False


def test_add_service_only_comment_wysyla_wlasciwy_komunikat():
    svc = _service_with_api()
    svc.add_service_only_comment_to_baselinker(5, "")
    assert "wyłącznie pozycje usługowe" in _sent_admin_comment(svc)


def test_add_validation_comment_zwraca_false_bez_bledow():
    svc = _service_with_api()
    assert svc.add_validation_comment_to_baselinker(5, [], "") is False
    svc._make_api_request.assert_not_called()
