# -*- coding: utf-8 -*-
"""
Budowanie konfiguracji zamówienia dla checkoutu klienckiego.

Panel składa `config` w JavaScripcie i wysyła w żądaniu; checkout nie ma
skąd go wziąć, więc buduje go serwerowo. Testujemy czystą funkcję na
SimpleNamespace, bez podnoszenia Flaska i bazy (jak tests/test_client_quote_api.py).
"""
import os
import sys
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.quotes.services.checkout_config import build_checkout_order_config  # noqa: E402


def _wycena(**nadpisania):
    dane = {
        "quote_type": "brutto",
        "courier_name": "DPD",
        "shipping_cost_netto": Decimal("100.00"),
        "shipping_cost_brutto": Decimal("123.00"),
    }
    dane.update(nadpisania)
    return SimpleNamespace(**dane)


class TestBuildCheckoutOrderConfig:
    def test_zrodlo_zamowien_trafia_do_konfiguracji(self):
        cfg = build_checkout_order_config(_wycena(), order_source_id=99001)
        assert cfg["order_source_id"] == 99001

    def test_sposob_dostawy_z_kuriera_wyceny(self):
        cfg = build_checkout_order_config(_wycena(courier_name="InPost"), order_source_id=1)
        assert cfg["delivery_method"] == "InPost"

    def test_brak_kuriera_daje_odbior_osobisty(self):
        cfg = build_checkout_order_config(_wycena(courier_name=None), order_source_id=1)
        assert cfg["delivery_method"] == "Odbiór osobisty"

    def test_wycena_brutto_wysyla_koszt_brutto(self):
        cfg = build_checkout_order_config(_wycena(quote_type="brutto"), order_source_id=1)
        assert cfg["shipping_cost_override"] == 123.00

    def test_wycena_netto_wysyla_koszt_netto(self):
        # Pozycje wyceny netto jadą do BL netto — koszt dostawy musi jechać tak samo,
        # inaczej suma zamówienia nie zgadza się z tym, co zaakceptował klient.
        cfg = build_checkout_order_config(_wycena(quote_type="netto"), order_source_id=1)
        assert cfg["shipping_cost_override"] == 100.00

    def test_brak_kosztu_wysylki_daje_zero(self):
        wycena = _wycena(shipping_cost_netto=None, shipping_cost_brutto=None)
        cfg = build_checkout_order_config(wycena, order_source_id=1)
        assert cfg["shipping_cost_override"] == 0.0

    def test_zalacznik_dolaczany(self):
        cfg = build_checkout_order_config(_wycena(), order_source_id=1)
        assert cfg["include_attachment"] is True

    def test_nie_przekazujemy_client_data(self):
        # Podanie client_data CAŁKOWICIE zastępuje dane z bazy (service.py:703-734),
        # bez mergowania pole po polu. Checkout zapisuje dane na Client PRZED
        # utworzeniem zamówienia, więc musi zostawić serwisowi odczyt z bazy.
        cfg = build_checkout_order_config(_wycena(), order_source_id=1)
        assert "client_data" not in cfg

    def test_kraj_dostawy_domyslnie_polska(self):
        cfg = build_checkout_order_config(_wycena(), order_source_id=1)
        assert cfg["delivery_country"] == "PL"

    def test_brak_pola_quote_type_domyslnie_brutto(self):
        # Serwis czyta tryb przez getattr z domyślnym 'brutto'
        # (modules/baselinker/service.py:527) — builder nie może wywracać się
        # na obiekcie bez tego pola, skoro serwis sobie z nim radzi.
        wycena = SimpleNamespace(
            courier_name="DPD",
            shipping_cost_netto=Decimal("100.00"),
            shipping_cost_brutto=Decimal("123.00"),
        )
        cfg = build_checkout_order_config(wycena, order_source_id=1)
        assert cfg["shipping_cost_override"] == 123.00


class TestOdbiorOsobisty:
    """Wybór „odbiór osobisty" musi dojechać do zamówienia.

    W panelu tę decyzję podejmował handlowiec ręcznie (baselinker.js:1568-1601);
    w ścieżce klienta nie podejmował jej nikt, więc zamówienie szło do
    BaseLinkera z kurierem i kosztem dostawy przy adresie „ODBIÓR OSOBISTY".
    Magazyn dostawał zlecenie „wyślij DPD na adres ODBIÓR OSOBISTY", a klient —
    obciążenie za dostawę, której odmówił.
    """

    def test_odbior_osobisty_zdejmuje_kuriera(self):
        cfg = build_checkout_order_config(_wycena(), order_source_id=1,
                                          is_self_pickup=True)
        assert cfg["delivery_method"] == "Odbiór osobisty"

    def test_odbior_osobisty_zeruje_koszt_dostawy(self):
        cfg = build_checkout_order_config(_wycena(), order_source_id=1,
                                          is_self_pickup=True)
        assert cfg["shipping_cost_override"] == 0.0

    def test_odbior_osobisty_zeruje_koszt_takze_w_wycenie_netto(self):
        cfg = build_checkout_order_config(_wycena(quote_type="netto"),
                                          order_source_id=1, is_self_pickup=True)
        assert cfg["shipping_cost_override"] == 0.0

    def test_bez_odbioru_osobistego_kurier_i_koszt_zostaja(self):
        # Kontrola negatywna: dostawa kurierska nie może zniknąć „przy okazji".
        cfg = build_checkout_order_config(_wycena(), order_source_id=1,
                                          is_self_pickup=False)
        assert cfg["delivery_method"] == "DPD"
        assert cfg["shipping_cost_override"] == 123.00

    def test_adres_odbioru_osobistego_na_kliencie_tez_zdejmuje_kuriera(self):
        # Wycena zaakceptowana wcześniej (np. starą ścieżką /accept-with-data)
        # nie przechodzi już przez zapis danych dostawy, więc jedynym śladem
        # wyboru jest znacznik zapisany na kliencie. Bez tego zamówienie
        # jechałoby kurierem pod adres „ODBIÓR OSOBISTY".
        wycena = _wycena(client=SimpleNamespace(delivery_address='ODBIÓR OSOBISTY'))
        cfg = build_checkout_order_config(wycena, order_source_id=1,
                                          is_self_pickup=False)
        assert cfg["delivery_method"] == "Odbiór osobisty"
        assert cfg["shipping_cost_override"] == 0.0

    def test_znacznik_bez_diakrytykow_tez_jest_rozpoznawany(self):
        wycena = _wycena(client=SimpleNamespace(delivery_address='Odbior osobisty'))
        cfg = build_checkout_order_config(wycena, order_source_id=1)
        assert cfg["delivery_method"] == "Odbiór osobisty"

    def test_zwykly_adres_dostawy_nie_udaje_odbioru(self):
        wycena = _wycena(client=SimpleNamespace(delivery_address='Leśna 12'))
        cfg = build_checkout_order_config(wycena, order_source_id=1)
        assert cfg["delivery_method"] == "DPD"
        assert cfg["shipping_cost_override"] == 123.00

    def test_wycena_bez_klienta_nie_wywraca_buildera(self):
        cfg = build_checkout_order_config(_wycena(), order_source_id=1)
        assert cfg["delivery_method"] == "DPD"
