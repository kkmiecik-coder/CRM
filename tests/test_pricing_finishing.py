"""Testy parytetu wykończenia z JS calculateFinishingCost (calculator-ui.js:493)."""
import math
from modules.calculator.services.pricing_service import (
    PricingData, calculate_finishing, _finishing_maps_from_flat_list,
)

OPCJE = {7: {'id': 7, 'price_netto': 200.0, 'full_path': 'Lakierowanie > Bezbarwne > Mat'}}


def _product(**kw):
    base = {'length': 100, 'width': 50, 'thickness': 3, 'quantity': 2,
            'shape': 'rectangular', 'finishing_type': 'Lakierowanie',
            'finishing_variant': 'Bezbarwne', 'finishing_gloss_level': 'Mat',
            'finishing_option_id': 7, 'finishing_full_path': 'Lakierowanie > Bezbarwne > Mat'}
    base.update(kw)
    return base


def test_surowe_zero():
    r = calculate_finishing(_product(finishing_type='Surowe'), PricingData())
    assert r['netto'] == 0 and r['brutto'] == 0


def test_prostokat():
    # powierzchnia = 2*(1*0.5 + 1*0.03 + 0.5*0.03) = 1.09 m2/szt * 2 szt = 2.18
    # netto = round(2.18*200) = 436.00; brutto = round(436*1.23) = 536.28
    r = calculate_finishing(_product(), PricingData(finishing_options_by_id=OPCJE))
    assert abs(r['surface_m2'] - 2.18) < 1e-9
    assert r['netto'] == 436.0
    assert r['brutto'] == 536.28


def test_round_elipsa():
    # shape='round': góra+dół 2*pi*a*b + obwód Ramanujana * grubość (JS 565-573)
    p = _product(shape='round', quantity=1)
    a, b = 0.5, 0.25
    top = 2 * math.pi * a * b
    per = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
    expected = top + per * 0.03
    r = calculate_finishing(p, PricingData(finishing_options_by_id=OPCJE))
    assert abs(r['surface_m2'] - expected) < 1e-9


def test_circle_liczy_jak_prostokat():
    # UWAGA: JS sprawdza tylko formShape === 'round' — circle wpada we wzór prostokąta.
    # Replikujemy 1:1 (Global Constraints: JS = źródło prawdy).
    r1 = calculate_finishing(_product(shape='circle'), PricingData(finishing_options_by_id=OPCJE))
    r2 = calculate_finishing(_product(shape='rectangular'), PricingData(finishing_options_by_id=OPCJE))
    assert r1['netto'] == r2['netto']


def test_lakierowanie_bez_polysku_zero():
    # JS: widoczna sekcja połysku bez wyboru -> 0 (calculator-ui.js:534-548)
    r = calculate_finishing(_product(finishing_gloss_level=None),
                            PricingData(finishing_options_by_id=OPCJE))
    assert r['netto'] == 0


# =============================================================================
# Testy _finishing_maps_from_flat_list — parytet z loadFinishingPrices()
# (calculator-ui.js:33-56). JS liczy na effective_price_netto (cena dziedziczona
# z rodzica gdy opcja nie ma własnej), NIE na surowym price_netto.
# =============================================================================

FLAT_LIST_RODZIC_DZIECKO = [
    {
        'id': 1, 'name': 'Lakierowanie', 'code': None, 'inherited_code': None,
        'full_path': 'Lakierowanie', 'level': 0, 'parent_id': None,
        'price_netto': 150.0, 'effective_price_netto': 150.0,
    },
    {
        # Dziecko BEZ własnej ceny (price_netto=None) — dziedziczy z rodzica.
        # To jest kluczowy przypadek problemu 2: musi mieć cenę w obu mapach.
        'id': 2, 'name': 'Bezbarwne', 'code': None, 'inherited_code': None,
        'full_path': 'Lakierowanie > Bezbarwne', 'level': 1, 'parent_id': 1,
        'price_netto': None, 'effective_price_netto': 150.0,
    },
    {
        'id': 3, 'name': 'Wycięcie', 'code': None, 'inherited_code': 'CUTOUT',
        'full_path': 'Wycięcie', 'level': 0, 'parent_id': None,
        'price_netto': None, 'effective_price_netto': 81.30,
    },
]


def test_finishing_maps_dziecko_bez_wlasnej_ceny_ma_cene_efektywna():
    by_id, by_path, cutout_price = _finishing_maps_from_flat_list(FLAT_LIST_RODZIC_DZIECKO)

    # Dziecko (id=2) nie ma własnej ceny, ale MUSI mieć effective_price_netto
    # w obu mapach — inaczej rozjedzie się z frontendem (bug parytetu).
    assert by_id[2]['price_netto'] == 150.0
    assert by_path['Lakierowanie > Bezbarwne'] == 150.0


def test_finishing_maps_klucz_legacy():
    by_id, by_path, cutout_price = _finishing_maps_from_flat_list(FLAT_LIST_RODZIC_DZIECKO)

    # JS: fullPath.replace(' > ', ' ') -> "Lakierowanie Bezbarwne" -> capitalize
    assert by_path['Lakierowanie bezbarwne'] == 150.0


def test_finishing_maps_level_zero_klucz_samej_nazwy():
    by_id, by_path, cutout_price = _finishing_maps_from_flat_list(FLAT_LIST_RODZIC_DZIECKO)

    # Opcja level==0 dodatkowo pod samą nazwą (JS:49-52)
    assert by_path['Lakierowanie'] == 150.0


def test_finishing_maps_cutout_po_inherited_code():
    by_id, by_path, cutout_price = _finishing_maps_from_flat_list(FLAT_LIST_RODZIC_DZIECKO)

    # code=None ale inherited_code='CUTOUT' -> musi zostać wykryte (JS:56)
    assert cutout_price == 81.30
