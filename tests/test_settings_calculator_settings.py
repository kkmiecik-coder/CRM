# -*- coding: utf-8 -*-
"""
Zbieranie ustawień kalkulatora z panelu Ustawień — waliduj wszystko,
zanim cokolwiek zapiszesz.

`_zbierz_ustawienia_kalkulatora` to czysta funkcja: dostaje słownik z żądania,
oddaje listę zapisów do wykonania DOPIERO po przejściu całej walidacji, albo
komunikat błędu. Dawniej dopłata za kształt okrągły była zapisywana do bazy
(CalculatorSetting.set_value() commituje wewnętrznie) PRZED walidacją pól
wysyłki — błędna wysyłka kończyła żądanie kodem 400, ale dopłata i tak
zostawała w bazie, a invalidate_pricing_cache() nigdy się nie wykonywało.
Te testy pilnują, żeby zapis następował wyłącznie wtedy, gdy CAŁE żądanie
jest poprawne.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.settings.routers import _zbierz_ustawienia_kalkulatora


# ── Same poprawne pola ──────────────────────────────────────────────────────

def test_sama_poprawna_doplata_ksztaltu_daje_jeden_zapis():
    zapisy, blad = _zbierz_ustawienia_kalkulatora({
        "round_shape_surcharge_netto": "42.50",
    })
    assert blad is None
    assert zapisy == [("round_shape_surcharge_netto", "42.50")]


def test_same_poprawne_ustawienia_wysylki_daja_cztery_zapisy():
    zapisy, blad = _zbierz_ustawienia_kalkulatora({
        "shipping_markup_percent": "30",
        "shipping_threshold_brutto": "150.00",
        "shipping_surcharge_brutto": "24.60",
        "shipping_surcharge_side": "below",
    })
    assert blad is None
    assert len(zapisy) == 4
    assert set(zapisy) == {
        ("shipping_markup_percent", 30.0),
        ("shipping_threshold_brutto", 150.0),
        ("shipping_surcharge_brutto", 24.6),
        ("shipping_surcharge_side", "below"),
    }


def test_doplata_i_wysylka_razem_daja_wszystkie_piec_zapisow():
    zapisy, blad = _zbierz_ustawienia_kalkulatora({
        "round_shape_surcharge_netto": "42.50",
        "shipping_markup_percent": "30",
        "shipping_threshold_brutto": "150.00",
        "shipping_surcharge_brutto": "24.60",
        "shipping_surcharge_side": "below",
    })
    assert blad is None
    assert len(zapisy) == 5
    assert set(zapisy) == {
        ("round_shape_surcharge_netto", "42.50"),
        ("shipping_markup_percent", 30.0),
        ("shipping_threshold_brutto", 150.0),
        ("shipping_surcharge_brutto", 24.6),
        ("shipping_surcharge_side", "below"),
    }


# ── Regresja: częściowo poprawne żądanie nie zapisuje NICZEGO ──────────────

def test_poprawna_doplata_z_niepoprawna_wysylka_nie_zapisuje_niczego():
    """To jest dokładnie scenariusz z findingu: poprawna dopłata za kształt
    razem z narzutem wysyłki spoza zakresu 0-500. Przed poprawką dopłata
    zdążyła się zapisać (set_value commituje od razu), zanim walidacja
    wysyłki zwróciła błąd. Po poprawce całe żądanie ma zostać odrzucone
    BEZ żadnego zapisu."""
    zapisy, blad = _zbierz_ustawienia_kalkulatora({
        "round_shape_surcharge_netto": "42.50",
        "shipping_markup_percent": "900",
    })
    assert zapisy is None
    assert blad is not None
    assert "0" in blad and "500" in blad


# ── Błędne wartości dopłaty za kształt ──────────────────────────────────────

def test_ujemna_doplata_zwraca_komunikat_o_ujemnej_wartosci():
    zapisy, blad = _zbierz_ustawienia_kalkulatora({
        "round_shape_surcharge_netto": "-5",
    })
    assert zapisy is None
    assert blad == "Dopłata nie może być ujemna"


def test_niepoprawna_liczbowo_doplata_zwraca_komunikat_o_nieprawidlowej_wartosci():
    zapisy, blad = _zbierz_ustawienia_kalkulatora({
        "round_shape_surcharge_netto": "abc",
    })
    assert zapisy is None
    assert blad == "Nieprawidłowa wartość dopłaty"


# ── Puste żądanie ────────────────────────────────────────────────────────────

def test_puste_zadanie_nie_daje_zapisow_ani_bledu():
    zapisy, blad = _zbierz_ustawienia_kalkulatora({})
    assert zapisy == []
    assert blad is None
