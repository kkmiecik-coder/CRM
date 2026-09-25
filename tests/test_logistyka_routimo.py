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


from datetime import date

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import routes, routimo
from tests.logistyka_fixtures import BASE, app, client, pojazd, zamowienie  # noqa: F401,E402


def test_wspolny_generator_to_te_same_naglowki():
    assert len(routimo.NAGLOWKI) == 37
    ark = _arkusz(routimo.zbuduj_excel([['x'] * 37]))
    assert [c.value for c in ark[1]] == routimo.NAGLOWKI


def _zatwierdzona(app):
    v = pojazd(name='Iveco KR 1')
    trasa = routes.utworz({'name': 'Kraków + Tarnów', 'date_from': '2026-10-01', 'vehicle_id': v.id})
    a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    a.delivery_address, a.delivery_postcode, a.client_phone = 'Floriańska 10/5', '31-021', '600'
    b = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    db.session.add(OrderGeo(order_id=a.id, lat=50.062726, lng=19.93962, source='gugik',
                            quality='dokladna', address_hash='x' * 40))
    routes.dodaj_przystanki(trasa, [b.id, a.id])
    routes.zatwierdz(trasa)
    db.session.commit()
    return trasa, a, b


def test_wiersze_trasy_w_kolejnosci_przystankow(app):
    with app.app_context():
        trasa, a, b = _zatwierdzona(app)
        wiersze = routimo.wiersze_trasy(trasa)
        assert [w[2] for w in wiersze] == [b.baselinker_order_id, a.baselinker_order_id]
        w = wiersze[1]
        assert (w[5], w[6], w[7], w[8]) == ('Floriańska', '10', '5', '31-021')
        assert w[20] == '2026-10-01' and w[22] == 'Iveco KR 1'
        assert (w[30], w[31]) == (50.062726, 19.93962)
        # PostcodeToStateMapper.get_state_from_postcode zwraca formę z wielkiej litery
        # (STATE_NORMALIZATION['małopolskie'] == 'Małopolskie') — nie 'małopolskie' jak w brief.
        assert w[11] == 'Małopolskie'
        assert wiersze[0][30] == ''       # bez współrzędnych — puste


def test_eksport_tylko_dla_zatwierdzonej(client, app):
    with app.app_context():
        trasa, _a, _b = _zatwierdzona(app)
        rid = trasa.id
        robocza = routes.utworz({'name': 'R', 'date_from': '2026-11-01'})
        db.session.commit()
        rid_roboczej = robocza.id
    r = client.get(BASE + '/routes/%d/routimo' % rid)
    assert r.status_code == 200
    assert r.headers['Content-Type'].startswith(
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    assert 'routimo_' in r.headers['Content-Disposition']
    assert client.get(BASE + '/routes/%d/routimo' % rid_roboczej).status_code == 409


def test_eksport_dla_wykonanej_trasy(client, app):
    """R11 (kontroler): eksport dostępny też dla trasy WYKONANEJ, nie tylko zatwierdzonej —
    przewoźnik może pobrać plik ponownie już po zamknięciu trasy."""
    with app.app_context():
        trasa, _a, _b = _zatwierdzona(app)
        routes.wykonaj(trasa)
        db.session.commit()
        rid = trasa.id
    r = client.get(BASE + '/routes/%d/routimo' % rid)
    assert r.status_code == 200


def test_eksport_404_dla_nieistniejacej_trasy(client):
    assert client.get(BASE + '/routes/999999/routimo').status_code == 404


def test_nazwa_pliku_transliteruje_polskie_znaki():
    """R10 (kontroler): polskie znaki zamienione na ASCII PRZED slugowaniem nazwy pliku."""
    trasa = NS(name='Kraków + Tarnów', date_from=date(2026, 10, 1))
    assert routimo.nazwa_pliku(trasa) == 'routimo_krakow-tarnow_2026-10-01.xlsx'


def test_nazwa_pliku_lodz():
    trasa = NS(name='Łódź', date_from=date(2026, 10, 1))
    assert routimo.nazwa_pliku(trasa) == 'routimo_lodz_2026-10-01.xlsx'


def test_nazwa_pliku_same_symbole_spada_na_trasa():
    trasa = NS(name='###???', date_from=date(2026, 10, 1))
    assert routimo.nazwa_pliku(trasa) == 'routimo_trasa_2026-10-01.xlsx'
