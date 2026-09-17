# -*- coding: utf-8 -*-
# Testy helperow wysylki: agregacja paczki (wymiary/waga) + wybor najtanszego
# kuriera wg konfigurowalnej formuly (shipping_pricing).
from modules.calculator.services.shipping_pricing import DEFAULT_CONFIG, SIDE_BELOW
from modules.calculator.services.shipping_service import (
    aggregate_package, cheapest_with_packing, serializuj_oferty,
)


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


def test_cheapest_with_packing_domyslnie_dolicza_30():
    """Konfiguracja domyślna = dotychczasowe zachowanie, co do grosza."""
    res = cheapest_with_packing([
        {"carrierName": "DPD", "grossPrice": 100.0, "netPrice": 81.30},
        {"carrierName": "InPost", "grossPrice": 80.0, "netPrice": 65.04},
    ], config=dict(DEFAULT_CONFIG))
    assert res["carrier_name"] == "InPost"
    assert res["shipping_brutto"] == 104.0     # 80 * 1.3
    assert res["shipping_netto"] == 84.55      # 104.0 / 1.23
    assert res["raw_brutto"] == 80.0


def test_cheapest_with_packing_wybiera_po_cenie_koncowej_nie_surowej():
    """Przy progu tańszy surowo kurier może złapać dopłatę i wyjść drożej.
    Klient płaci cenę końcową i to ona decyduje o wyborze.

    A: 90 -> 117 -> poniżej progu 130 -> +20 = 137
    B: 101 -> 131,30 -> od progu w górę -> bez dopłaty = 131,30
    """
    config = dict(DEFAULT_CONFIG)
    config.update(threshold_brutto=130.0, surcharge_brutto=20.0, side=SIDE_BELOW)

    res = cheapest_with_packing([
        {"carrierName": "A", "grossPrice": 90.0, "netPrice": 73.17},
        {"carrierName": "B", "grossPrice": 101.0, "netPrice": 82.11},
    ], config=config)

    assert res["carrier_name"] == "B"
    assert res["shipping_brutto"] == 131.30
    assert res["raw_brutto"] == 101.0


def test_cheapest_with_packing_pomija_oferty_bez_ceny_liczbowej():
    res = cheapest_with_packing([
        {"carrierName": "Bez ceny", "grossPrice": "na zapytanie"},
        {"carrierName": "DPD", "grossPrice": 100.0, "netPrice": 81.30},
    ], config=dict(DEFAULT_CONFIG))
    assert res["carrier_name"] == "DPD"


def test_cheapest_with_packing_odrzuca_bool_ceny():
    """bool jest w Pythonie podklasą int, więc samo isinstance(x, (int, float))
    przepuszcza True — i bot policzyłby taką ofertę jako 1 zł, czyli najtańszą.
    serializuj_oferty odsiewa to u źródła, ale ta funkcja bierze listę
    podaną przez wywołującego, więc musi bronić się sama tym samym warunkiem."""
    res = cheapest_with_packing([
        {"carrierName": "Zepsuty", "grossPrice": True},
        {"carrierName": "DPD", "grossPrice": 100.0, "netPrice": 81.30},
    ], config=dict(DEFAULT_CONFIG))
    assert res["carrier_name"] == "DPD"
    assert res["raw_brutto"] == 100.0


def test_cheapest_with_packing_pusto_daje_none():
    assert cheapest_with_packing([]) is None


# ── serializuj_oferty: oferta bez liczbowej ceny nie wychodzi z serwisu ────
# (item 2 przeglądu). cheapest_with_packing (bot) już się broni filtrem
# isinstance — get_shipping_quotes (panel/kalkulator) budował wynik bez
# takiej ochrony: oferta z grossPrice="" leciała do _liczba() w
# apply_shipping_markup i wychodziła jako 0,00 zł — najtańsza i wybieralna.

def test_serializuj_oferty_zachowuje_oferte_z_liczbowa_cena():
    wynik = serializuj_oferty([
        {"carrierName": "DPD", "grossPrice": 100.0, "carrierLogoLink": "dpd.png"},
    ])
    assert wynik == [{
        "carrierName": "DPD",
        "grossPrice": 100.0,
        "netPrice": round(100.0 / 1.23, 2),
        "carrierLogoLink": "dpd.png",
    }]


def test_serializuj_oferty_odrzuca_pusty_string_ceny():
    wynik = serializuj_oferty([
        {"carrierName": "Na zapytanie", "grossPrice": ""},
        {"carrierName": "DPD", "grossPrice": 100.0},
    ])
    assert [oferta["carrierName"] for oferta in wynik] == ["DPD"]


def test_serializuj_oferty_odrzuca_none_ceny():
    wynik = serializuj_oferty([{"carrierName": "Brak", "grossPrice": None}])
    assert wynik == []


def test_serializuj_oferty_odrzuca_bool_ceny():
    """bool to w Pythonie podklasa int — isinstance(True, (int, float)) samo
    w sobie by go przepuściło, trzeba wykluczyć jawnie."""
    wynik = serializuj_oferty([{"carrierName": "Dziwna", "grossPrice": True}])
    assert wynik == []


def test_serializuj_oferty_brakujace_pola_dostaja_wartosci_domyslne():
    wynik = serializuj_oferty([{"grossPrice": 61.50}])
    assert wynik == [{
        "carrierName": "Nieznany",
        "grossPrice": 61.50,
        "netPrice": 50.0,
        "carrierLogoLink": "",
    }]
