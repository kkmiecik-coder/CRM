"""Testy parytetu wykończenia z JS calculateFinishingCost (calculator-ui.js:493)."""
import math
from modules.calculator.services.pricing_service import PricingData, calculate_finishing

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
