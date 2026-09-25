# -*- coding: utf-8 -*-
import io
from types import SimpleNamespace as NS

import openpyxl

from modules.reports.routers import generate_routimo_excel

GRUPA = [{
    'records': [NS(raw_product_name='Blat dębowy 200x60x4', quantity=2),
                NS(raw_product_name='Parapet 100x30x3', quantity=1)],
    'baselinker_order_id': 12345, 'internal_order_number': '26/00042',
    'customer_name': 'Jan Kowalski', 'delivery_address': 'ul. Floriańska 10/5',
    'delivery_postcode': '31-021', 'delivery_city': 'Kraków', 'delivery_state': 'małopolskie',
    'phone': '600100200', 'email': 'jan@example.com', 'delivery_cost': 123.0,
    'payment_method': 'Przelew', 'order_amount_net': 2000.0, 'total_quantity': 3,
    'total_volume': 0.1, 'total_value_net': 2000.0, 'current_status': 'x',
}]


def _arkusz(tresc):
    return openpyxl.load_workbook(io.BytesIO(tresc)).active


def test_stary_eksport_routimo_bez_zmian():
    """Charakterystyka: przechodzi PRZED i PO wydzieleniu generatora."""
    ark = _arkusz(generate_routimo_excel(GRUPA))
    naglowki = [c.value for c in ark[1]]
    assert len(naglowki) == 37 and naglowki[0] == 'Nazwa' and naglowki[-1] == 'Dodatkowe 2'
    wiersz = [c.value for c in ark[2]]
    assert wiersz[:10] == ['Jan Kowalski', 'Jan Kowalski', 12345, '26/00042', 100.0,
                           'Floriańska', '10', '5', '31-021', 'Kraków']
    assert wiersz[26] == 80.0            # waga = 0.1 m³ × 800
    assert wiersz[32] == 'Blat dębowy 200x60x4 x2\nParapet 100x30x3 x1'
    assert wiersz[33] == '12345, 26/00042'
    assert ark.column_dimensions['A'].width == 40.0
    assert ark.row_dimensions[1].height == 43.0
    assert ark[1][0].font.bold and ark[2][32].alignment.wrap_text
    assert ark.parent.sheetnames == ['Sheet1', 'Sheet2']
