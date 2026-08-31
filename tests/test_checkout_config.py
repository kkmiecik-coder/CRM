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

import pytest  # noqa: E402

from modules.quotes.services.checkout_config import (  # noqa: E402
    KonfliktDostawy, build_checkout_order_config,
)


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

    def test_kurier_w_formularzu_przy_znaczniku_odbioru_to_odmowa(self):
        # Dawniej odbiór osobisty wygrywał tu po cichu: klient prosił o kuriera,
        # a zamówienie szło jako odbiór, więc czekał na przesyłkę, która nigdy
        # nie wyjechała. Honorowanie kuriera wymagałoby WYMYŚLENIA adresu —
        # z pól formularza, których ta ścieżka nie zapisuje i nikt nie
        # zweryfikował. Odmawiamy.
        wycena = _wycena(client=SimpleNamespace(delivery_address='ODBIÓR OSOBISTY'))
        with pytest.raises(KonfliktDostawy):
            build_checkout_order_config(wycena, order_source_id=1,
                                        is_self_pickup=False)

    def test_znacznik_bez_diakrytykow_tez_jest_rozpoznawany(self):
        # Ten sam konflikt, znacznik zapisany bez polskich znaków.
        wycena = _wycena(client=SimpleNamespace(delivery_address='Odbior osobisty'))
        with pytest.raises(KonfliktDostawy):
            build_checkout_order_config(wycena, order_source_id=1)

    def test_zgodny_odbior_osobisty_po_obu_stronach_przechodzi(self):
        # Kontrola negatywna: gdy oba źródła mówią to samo, nie ma konfliktu.
        wycena = _wycena(client=SimpleNamespace(delivery_address='ODBIÓR OSOBISTY'))
        cfg = build_checkout_order_config(wycena, order_source_id=1,
                                          is_self_pickup=True)
        assert cfg["delivery_method"] == "Odbiór osobisty"
        assert cfg["shipping_cost_override"] == 0.0
        # Adres na kliencie JEST już znacznikiem odbioru — nie ma czego zdejmować.
        assert "delivery_override" not in cfg

    def test_odbior_w_formularzu_przy_realnym_adresie_zdejmuje_adres(self):
        # Świeża decyzja klienta wygrywa, ale zamówienie musi być spójne:
        # metoda „Odbiór osobisty" + zerowa dostawa + PEŁNY adres kurierski
        # to sprzeczne zlecenie dla magazynu i darmowa wysyłka.
        wycena = _wycena(client=SimpleNamespace(delivery_address='Leśna 12',
                                                delivery_city='Gdańsk'))
        cfg = build_checkout_order_config(wycena, order_source_id=1,
                                          is_self_pickup=True)
        assert cfg["delivery_method"] == "Odbiór osobisty"
        assert cfg["shipping_cost_override"] == 0.0
        assert cfg["delivery_override"]["delivery_address"] == 'ODBIÓR OSOBISTY'
        assert cfg["delivery_override"]["delivery_city"] == 'ODBIÓR OSOBISTY'
        assert cfg["delivery_override"]["delivery_postcode"] == ''

    def test_kurier_przy_realnym_adresie_nie_zdejmuje_niczego(self):
        # Kontrola negatywna: dostawa kurierska nie może gubić adresu.
        wycena = _wycena(client=SimpleNamespace(delivery_address='Leśna 12'))
        cfg = build_checkout_order_config(wycena, order_source_id=1,
                                          is_self_pickup=False)
        assert cfg["delivery_method"] == "DPD"
        assert "delivery_override" not in cfg

    def test_zwykly_adres_dostawy_nie_udaje_odbioru(self):
        wycena = _wycena(client=SimpleNamespace(delivery_address='Leśna 12'))
        cfg = build_checkout_order_config(wycena, order_source_id=1)
        assert cfg["delivery_method"] == "DPD"
        assert cfg["shipping_cost_override"] == 123.00

    def test_wycena_bez_klienta_nie_wywraca_buildera(self):
        cfg = build_checkout_order_config(_wycena(), order_source_id=1)
        assert cfg["delivery_method"] == "DPD"


class TestKurierJakWWycenie:
    """Trzecie wyjście z konfliktu: wycena niesie kuriera, więc ona rozstrzyga.

    Znacznik „ODBIÓR OSOBISTY" siedzi na WSPÓŁDZIELONYM rekordzie klienta —
    zostaje tam po każdej wycenie odebranej osobiście i obowiązuje wszystkie
    następne. Dopóki jedynymi wyjściami były odmowa i darmowa wysyłka, wycena
    kurierska takiego klienta kończyła się albo telefonem do biura, albo utratą
    kosztu dostawy. Wycena wie, jakim kurierem i za ile — i to ona ma tu
    rozstrzygać.

    Adres nadal nie jest WYMYŚLANY: jedzie ten, który klient wpisał w tym samym
    formularzu (ta sama bramka tożsamości co przy akceptacji). Gdy formularz
    adresu nie niesie, zostaje odmowa — przesyłka pod znacznik „ODBIÓR
    OSOBISTY" byłaby gorsza od braku zamówienia.
    """

    ADRES_Z_FORMULARZA = {
        'delivery_name': 'Jan Testowy',
        'delivery_address': 'Nowa 5',
        'delivery_postcode': '00-001',
        'delivery_city': 'Warszawa',
        'delivery_region': 'mazowieckie',
        'delivery_company': 'Firma',
    }

    def _wycena_ze_znacznikiem(self, **nadpisania):
        return _wycena(client=SimpleNamespace(delivery_address='ODBIÓR OSOBISTY',
                                              delivery_city='ODBIÓR OSOBISTY'),
                       **nadpisania)

    def test_kurier_z_wyceny_wygrywa_ze_stalym_znacznikiem_odbioru(self):
        cfg = build_checkout_order_config(
            self._wycena_ze_znacznikiem(), order_source_id=1,
            is_self_pickup=False,
            dane_dostawy_z_formularza=self.ADRES_Z_FORMULARZA)

        assert cfg["delivery_method"] == "DPD"
        assert cfg["shipping_cost_override"] == 123.00

    def test_adres_bierze_sie_z_formularza_a_nie_ze_znacznika(self):
        # Znacznik odbioru NIE MOŻE pojechać jako adres przesyłki kurierskiej.
        cfg = build_checkout_order_config(
            self._wycena_ze_znacznikiem(), order_source_id=1,
            is_self_pickup=False,
            dane_dostawy_z_formularza=self.ADRES_Z_FORMULARZA)

        nadpisanie = cfg["delivery_override"]
        assert nadpisanie["delivery_address"] == 'Nowa 5'
        assert nadpisanie["delivery_city"] == 'Warszawa'
        assert nadpisanie["delivery_postcode"] == '00-001'
        assert 'ODBIÓR' not in str(nadpisanie).upper()

    def test_bez_adresu_w_formularzu_zostaje_odmowa(self):
        # Nie ma dokąd wysłać — a zamówienie kurierskie pod znacznik odbioru
        # to przesyłka, która nigdy nie dojdzie.
        with pytest.raises(KonfliktDostawy):
            build_checkout_order_config(self._wycena_ze_znacznikiem(),
                                        order_source_id=1, is_self_pickup=False,
                                        dane_dostawy_z_formularza={})

    def test_niepelny_adres_w_formularzu_to_odmowa(self):
        with pytest.raises(KonfliktDostawy):
            build_checkout_order_config(
                self._wycena_ze_znacznikiem(), order_source_id=1,
                is_self_pickup=False,
                dane_dostawy_z_formularza={'delivery_address': 'Nowa 5'})

    def test_wycena_bez_kuriera_nie_ma_czym_rozstrzygnac(self):
        # Wycena nie niesie danych dostawy, więc nie ma trzeciego wyjścia:
        # zostaje odmowa, dokładnie jak przed tą zmianą.
        with pytest.raises(KonfliktDostawy):
            build_checkout_order_config(
                self._wycena_ze_znacznikiem(courier_name=None),
                order_source_id=1, is_self_pickup=False,
                dane_dostawy_z_formularza=self.ADRES_Z_FORMULARZA)

    def test_kurier_o_nazwie_odbior_osobisty_to_nie_kurier(self):
        # Panel wpisuje tę samą nazwę przy odbiorze osobistym — takiej wyceny
        # nie wolno czytać jako kurierskiej.
        with pytest.raises(KonfliktDostawy):
            build_checkout_order_config(
                self._wycena_ze_znacznikiem(courier_name='Odbiór osobisty'),
                order_source_id=1, is_self_pickup=False,
                dane_dostawy_z_formularza=self.ADRES_Z_FORMULARZA)

    def test_odbior_z_formularza_nadal_wygrywa_na_wycenie_kurierskiej(self):
        # Kontrola negatywna: świeży wybór klienta „odbieram osobiście" zostaje
        # uszanowany i NIE zamienia się w rachunek za kuriera.
        cfg = build_checkout_order_config(
            self._wycena_ze_znacznikiem(), order_source_id=1, is_self_pickup=True,
            dane_dostawy_z_formularza=self.ADRES_Z_FORMULARZA)

        assert cfg["delivery_method"] == "Odbiór osobisty"
        assert cfg["shipping_cost_override"] == 0.0

    def test_realny_adres_na_kliencie_nie_jest_nadpisywany_formularzem(self):
        # Kontrola negatywna: bez konfliktu formularz nie ma prawa podmieniać
        # adresu — zamówienie jedzie pod adres zapisany na kliencie.
        wycena = _wycena(client=SimpleNamespace(delivery_address='Leśna 12'))

        cfg = build_checkout_order_config(
            wycena, order_source_id=1, is_self_pickup=False,
            dane_dostawy_z_formularza=self.ADRES_Z_FORMULARZA)

        assert "delivery_override" not in cfg
