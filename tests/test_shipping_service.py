# -*- coding: utf-8 -*-
# Testy helperow wysylki: agregacja paczki (wymiary/waga) + wybor najtanszego kuriera +30%.
from modules.calculator.services.shipping_service import (
    aggregate_package, cheapest_with_packing, PACKING_MULTIPLIER,
)


def test_packing_multiplier_to_1_3():
    assert PACKING_MULTIPLIER == 1.3


def test_aggregate_package_pojedynczy_blat():
    pkg = aggregate_package([{"length": 200, "width": 60, "thickness": 4, "quantity": 2}])
    assert pkg["length"] == 205        # 200 + 5
    assert pkg["width"] == 65           # 60 + 5
    assert pkg["height"] == 13          # 4*2 + 5
    # waga: 200*60*4/1e6 = 0.048 m3 * 800 = 38.4 kg * 2 szt = 76.8
    assert pkg["weight"] == 76.8
    assert pkg["quantity"] == 1
    assert pkg["senderCountryId"] == "1" and pkg["receiverCountryId"] == "1"


def test_aggregate_package_wiele_pozycji_max_i_suma_grubosci():
    pkg = aggregate_package([
        {"length": 140, "width": 80, "thickness": 3, "quantity": 1},
        {"length": 200, "width": 60, "thickness": 4, "quantity": 1},
    ])
    assert pkg["length"] == 205        # max(140,200) + 5
    assert pkg["width"] == 85           # max(80,60) + 5
    assert pkg["height"] == 12          # (3+4) + 5


def test_aggregate_package_pomija_pozycje_bez_wymiarow():
    pkg = aggregate_package([
        {"length": 0, "width": 60, "thickness": 4, "quantity": 1},
        {"length": 100, "width": 50, "thickness": 3, "quantity": 1},
    ])
    assert pkg["length"] == 105        # tylko druga pozycja (pierwsza ma length=0)


def test_cheapest_with_packing_wybiera_najtansza_i_dolicza_30():
    res = cheapest_with_packing([
        {"carrierName": "DPD", "grossPrice": 100.0, "netPrice": 81.30},
        {"carrierName": "InPost", "grossPrice": 80.0, "netPrice": 65.04},
    ])
    assert res["carrier_name"] == "InPost"
    assert res["shipping_brutto"] == 104.0     # 80 * 1.3
    assert res["shipping_netto"] == 84.55      # 65.04 * 1.3 = 84.552 -> 84.55
    assert res["raw_brutto"] == 80.0


def test_cheapest_with_packing_pusto_daje_none():
    assert cheapest_with_packing([]) is None
