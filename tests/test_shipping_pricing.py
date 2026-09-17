# -*- coding: utf-8 -*-
"""
Formuła wyliczania wysyłki — narzut procentowy + dopłata progowa.

Te testy są jedynym miejscem, które pilnuje, że wartości domyślne odtwarzają
dzisiejsze zaszyte na sztywno +30%. Utrata tej własności oznacza cichą zmianę
cen wysyłki we WSZYSTKICH wycenach po deployu.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.calculator.services.shipping_pricing import (
    DEFAULT_CONFIG,
    SIDE_ABOVE,
    SIDE_BELOW,
    _procent,
    apply_shipping_markup,
    build_markup_payload,
    describe_shipping_markup,
    parse_markup_request,
    sanitize_shipping_config,
    validate_shipping_settings,
)


def _config(**nadpisania):
    """Konfiguracja domyślna z punktowymi zmianami — skrót na potrzeby testów."""
    dane = dict(DEFAULT_CONFIG)
    dane.update(nadpisania)
    return dane


# ── Regresja: domyślne wartości = dzisiejsze x 1.3 ──────────────────────────

def test_domyslna_konfiguracja_odtwarza_dzisiejsze_30_procent():
    wynik = apply_shipping_markup(80.0, _config())
    assert wynik["final_brutto"] == 104.0        # 80 * 1.3
    assert wynik["surcharge_brutto"] == 0.0
    assert wynik["markup_brutto"] == 24.0


def test_domyslna_konfiguracja_nie_dolicza_kwoty_mimo_progu_zero():
    """prog=0 i strona 'below': warunek cena < 0 nigdy nie zachodzi."""
    wynik = apply_shipping_markup(10.0, _config(surcharge_brutto=25.0))
    assert wynik["surcharge_brutto"] == 0.0
    assert wynik["final_brutto"] == 13.0


# ── Próg i strona dopłaty ───────────────────────────────────────────────────

def test_ponizej_progu_dostaje_doplate():
    wynik = apply_shipping_markup(61.50, _config(
        threshold_brutto=150.0, surcharge_brutto=24.60, side=SIDE_BELOW))
    assert wynik["markup_brutto"] == 18.45       # 61.50 * 0.3
    assert wynik["surcharge_brutto"] == 24.60
    assert wynik["final_brutto"] == 104.55       # 79.95 + 24.60


def test_powyzej_progu_nie_dostaje_doplaty_przy_stronie_below():
    wynik = apply_shipping_markup(200.0, _config(
        threshold_brutto=150.0, surcharge_brutto=24.60, side=SIDE_BELOW))
    assert wynik["surcharge_brutto"] == 0.0
    assert wynik["final_brutto"] == 260.0


def test_strona_above_dolicza_od_progu_w_gore():
    wynik = apply_shipping_markup(200.0, _config(
        threshold_brutto=150.0, surcharge_brutto=24.60, side=SIDE_ABOVE))
    assert wynik["surcharge_brutto"] == 24.60
    assert wynik["final_brutto"] == 284.60


def test_strona_above_nie_dolicza_ponizej_progu():
    wynik = apply_shipping_markup(61.50, _config(
        threshold_brutto=150.0, surcharge_brutto=24.60, side=SIDE_ABOVE))
    assert wynik["surcharge_brutto"] == 0.0


def test_cena_rowna_progowi_nalezy_do_od_progu_w_gore():
    """100 * 1.3 = 130 = prog. Strona 'above' dolicza, 'below' nie."""
    above = apply_shipping_markup(100.0, _config(
        threshold_brutto=130.0, surcharge_brutto=10.0, side=SIDE_ABOVE))
    below = apply_shipping_markup(100.0, _config(
        threshold_brutto=130.0, surcharge_brutto=10.0, side=SIDE_BELOW))
    assert above["surcharge_brutto"] == 10.0
    assert below["surcharge_brutto"] == 0.0


def test_prog_mierzy_cene_po_procencie_a_nie_surowa():
    """Surowa 100 jest PONIŻEJ progu 120, ale po narzucie 130 jest POWYŻEJ.
    Decyduje cena po procencie, więc dopłata 'below' się NIE należy."""
    wynik = apply_shipping_markup(100.0, _config(
        threshold_brutto=120.0, surcharge_brutto=15.0, side=SIDE_BELOW))
    assert wynik["surcharge_brutto"] == 0.0
    assert wynik["final_brutto"] == 130.0


# ── Netto ───────────────────────────────────────────────────────────────────

def test_netto_to_brutto_podzielone_przez_vat():
    wynik = apply_shipping_markup(61.50, _config(
        threshold_brutto=150.0, surcharge_brutto=24.60, side=SIDE_BELOW))
    assert wynik["raw_netto"] == 50.0            # 61.50 / 1.23
    assert wynik["final_netto"] == 85.0          # 104.55 / 1.23


# ── Sanityzacja: zepsuta baza nie może wywrócić wyceny ──────────────────────

def test_sanitize_smieciowe_wartosci_wracaja_do_domyslnych():
    wynik = sanitize_shipping_config({
        "percent": "bardzo duzo",
        "threshold_brutto": -5,
        "surcharge_brutto": None,
        "side": "na_ukos",
    })
    assert wynik == DEFAULT_CONFIG


def test_sanitize_odrzuca_procent_powyzej_limitu():
    assert sanitize_shipping_config({"percent": "10000"})["percent"] == 30.0


def test_sanitize_czyta_stringi_z_bazy():
    wynik = sanitize_shipping_config({
        "percent": "27.5", "threshold_brutto": "150.00",
        "surcharge_brutto": "24.60", "side": " ABOVE ",
    })
    assert wynik == {"percent": 27.5, "threshold_brutto": 150.0,
                     "surcharge_brutto": 24.6, "side": SIDE_ABOVE}


def test_sanitize_pustego_wejscia_daje_domyslne():
    assert sanitize_shipping_config(None) == DEFAULT_CONFIG


# ── Opis tekstowy dla modala ────────────────────────────────────────────────

def test_opis_bez_doplaty_mowi_tylko_o_procencie():
    assert describe_shipping_markup(_config()) == \
        "Do cen wysyłki doliczono 30% na pakowanie."


def test_opis_z_doplata_ponizej_progu():
    opis = describe_shipping_markup(_config(
        threshold_brutto=150.0, surcharge_brutto=24.60, side=SIDE_BELOW))
    assert opis == ("Do cen wysyłki doliczono 30% na pakowanie "
                    "oraz 24,60 zł przy cenie poniżej 150,00 zł.")


def test_opis_z_doplata_od_progu_w_gore():
    opis = describe_shipping_markup(_config(
        threshold_brutto=150.0, surcharge_brutto=24.60, side=SIDE_ABOVE))
    assert opis == ("Do cen wysyłki doliczono 30% na pakowanie "
                    "oraz 24,60 zł przy cenie od 150,00 zł.")


def test_opis_procentu_ulamkowego_bez_zbednych_zer():
    assert "27,5%" in describe_shipping_markup(_config(percent=27.5))


# ── Payload endpointu ───────────────────────────────────────────────────────

def test_build_markup_payload_zachowuje_kolejnosc_wejscia():
    payload = build_markup_payload([80.0, 61.50], _config())
    assert [pozycja["raw_brutto"] for pozycja in payload["items"]] == [80.0, 61.5]
    assert payload["items"][0]["final_brutto"] == 104.0
    assert payload["config"]["percent"] == 30.0
    assert payload["info"].startswith("Do cen wysyłki")


# ── percent_label: jedyne miejsce formatowania procentu (item 1 przeglądu) ──
# formatPercent() w calculator-delivery.js formatował tę samą liczbę DRUGI
# raz, po swojemu (toFixed, zaokrąglanie od zera) — przy remisie (np. 0.125)
# rozjeżdżało się to z zaokrągleniem bankierskim Pythona. Backend ma być
# teraz JEDYNYM miejscem, które zamienia procent na tekst.

def test_build_markup_payload_dodaje_percent_label():
    payload = build_markup_payload([80.0], _config())
    assert payload["config"]["percent_label"] == _procent(30.0)
    assert payload["config"]["percent_label"] == "30%"


def test_build_markup_payload_percent_label_dla_procentu_ulamkowego():
    payload = build_markup_payload([80.0], _config(percent=27.5))
    assert payload["config"]["percent_label"] == _procent(27.5)
    assert payload["config"]["percent_label"] == "27,5%"


def test_build_markup_payload_nie_mutuje_przekazanej_konfiguracji():
    """`config` to ten sam słownik, którego apply_shipping_markup używa do
    arytmetyki dla każdej pozycji w tym samym wywołaniu — dopisanie
    percent_label MUSI trafić do kopii, nie do oryginału, inaczej dokładamy
    pole do cudzego słownika jako efekt uboczny."""
    config = _config()
    kopia_przed = dict(config)
    build_markup_payload([80.0], config)
    assert config == kopia_przed


# ── Walidacja wejścia z panelu Ustawień ─────────────────────────────────────

def test_validate_przepuszcza_poprawne_wartosci():
    czyste, blad = validate_shipping_settings({
        "shipping_markup_percent": "30",
        "shipping_threshold_brutto": "150.00",
        "shipping_surcharge_brutto": "24.60",
        "shipping_surcharge_side": "below",
    })
    assert blad is None
    assert czyste == {
        "shipping_markup_percent": 30.0,
        "shipping_threshold_brutto": 150.0,
        "shipping_surcharge_brutto": 24.6,
        "shipping_surcharge_side": "below",
    }


def test_validate_pomija_klucze_nieobecne_w_zadaniu():
    """Panel wysyła tylko swoje pola — zapis dopłaty za kształt okrągły
    nie może przypadkiem wyzerować ustawień wysyłki."""
    czyste, blad = validate_shipping_settings({"round_shape_surcharge_netto": "50"})
    assert blad is None
    assert czyste == {}


def test_validate_odrzuca_procent_spoza_zakresu():
    czyste, blad = validate_shipping_settings({"shipping_markup_percent": "900"})
    assert czyste is None
    assert "0" in blad and "500" in blad


def test_validate_odrzuca_kwote_ujemna():
    czyste, blad = validate_shipping_settings({"shipping_surcharge_brutto": "-1"})
    assert czyste is None
    assert "nieujemn" in blad


def test_validate_odrzuca_nieznana_strone():
    czyste, blad = validate_shipping_settings({"shipping_surcharge_side": "obok"})
    assert czyste is None
    assert blad


def test_validate_odrzuca_tekst_w_progu():
    czyste, blad = validate_shipping_settings({"shipping_threshold_brutto": "sto"})
    assert czyste is None
    assert blad


# ── Parsowanie żądania /api/shipping-markup ─────────────────────────────────
# request.get_json(silent=True) potrafi zwrócić cokolwiek syntaktycznie
# poprawnego jako JSON — nie tylko słownik albo None. Bez sprawdzenia typu
# payload.get('gross_prices') wywala AttributeError na gołej liście, liczbie
# czy stringu (silent=True łapie tylko błąd parsowania, nie zły typ).

def test_parse_markup_request_przepuszcza_poprawny_payload():
    ceny, blad = parse_markup_request({"gross_prices": [80.0, 61.50]})
    assert blad is None
    assert ceny == [80.0, 61.50]


def test_parse_markup_request_odrzuca_payload_ktory_nie_jest_slownikiem():
    """Ciało żądania to np. gola lista JSON — nie ma .get(), więc stary kod
    wywalał tu AttributeError zamiast zwrócić 400."""
    ceny, blad = parse_markup_request([1, 2, 3])
    assert ceny is None
    assert blad == "Brak cen do przeliczenia."


def test_parse_markup_request_odrzuca_brak_jsona():
    """request.get_json(silent=True) zwraca None przy pustym/niepoprawnym
    body — to też nie jest słownikiem."""
    ceny, blad = parse_markup_request(None)
    assert ceny is None
    assert blad == "Brak cen do przeliczenia."


def test_parse_markup_request_odrzuca_brak_pola_gross_prices():
    ceny, blad = parse_markup_request({})
    assert ceny is None
    assert blad == "Brak cen do przeliczenia."


def test_parse_markup_request_odrzuca_gross_prices_ktore_nie_jest_lista():
    ceny, blad = parse_markup_request({"gross_prices": "80.0"})
    assert ceny is None
    assert blad == "Brak cen do przeliczenia."


def test_parse_markup_request_odrzuca_pusta_liste_cen():
    ceny, blad = parse_markup_request({"gross_prices": []})
    assert ceny is None
    assert blad == "Brak cen do przeliczenia."
