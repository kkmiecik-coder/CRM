# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import delivery, routes
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.services.label_print_service import _format_delivery_label
from modules.production.services.mobile_api_service import serialize_order
from tests.logistyka_fixtures import BASE, app, client, pojazd, zamowienie  # noqa: F401


def _na_trasie(status='robocza', statusy=('spakowane',)):
    v = pojazd(name='Iveco KR 1')
    trasa = routes.utworz({'name': 'Kraków + Tarnów', 'date_from': '2026-10-01',
                           'vehicle_id': v.id})
    order = zamowienie(sposob=s.TRANSPORT, statusy=statusy)
    routes.dodaj_przystanki(trasa, [order.id])
    if status in ('zatwierdzona', 'wykonana'):
        routes.zatwierdz(trasa)
    if status == 'wykonana':
        routes.wykonaj(trasa)
    db.session.commit()
    return trasa, order


def test_zmiana_sposobu_zdejmuje_z_roboczej(app):
    """Review Focus 2."""
    with app.app_context():
        trasa, order = _na_trasie('robocza')
        wynik = delivery.ustaw_sposob_dostawy(order, s.ODBIOR)
        db.session.commit()
        assert wynik['usunieto_z_trasy'] == 'Kraków + Tarnów'
        assert routes.przystanek_zamowienia(order.id) is None


def test_zmiana_sposobu_na_zatwierdzonej_to_409(app):
    with app.app_context():
        _trasa, order = _na_trasie('zatwierdzona')
        with pytest.raises(LogistykaBlad) as e:
            delivery.ustaw_sposob_dostawy(order, s.KURIER)
        assert e.value.status == 409 and 'cofnij' in e.value.komunikat


def test_zmiana_sposobu_dostarczonego_to_409(app):
    with app.app_context():
        _trasa, order = _na_trasie('wykonana')
        assert order.logistics_closed_at is not None
        with pytest.raises(LogistykaBlad):
            delivery.ustaw_sposob_dostawy(order, s.ODBIOR)


def test_tablet_widzi_trase_i_etykieta_tez(app):
    with app.app_context():
        trasa, order = _na_trasie('robocza', statusy=('czeka_na_pakowanie',))
        with app.test_request_context():
            dane = serialize_order(order.products[0], station_code='packaging')
        assert dane['transport'] == {'mode': 'wlasny', 'trip_name': 'Kraków + Tarnów',
                                     'trip_date': '2026-10-01', 'vehicle_name': 'Iveco KR 1',
                                     'repack_required': False}
        assert _format_delivery_label(order.products[0]) == 'Krakow + Tarnow' or \
            _format_delivery_label(order.products[0]).startswith('Krak')


def test_tablet_traci_trase_po_zdjeciu(app):
    """Review Focus 3.

    (fix-1) Sprzed rundy poprawek `assert updated_at >= przed` nie mógł nigdy paść:
    `przed` to znacznik, który `dodaj_przystanki` sam przed chwilą zapisał — gdyby
    `usun_przystanek` przestał podbijać `updated_at`, wartość zostałaby taka sama
    i `>=` nadal by przeszło. Wzorzec z Task 3: cofamy znacznik na stałą przeszłą
    datę, potem wymagamy ścisłego „nowszy niż”.
    """
    with app.app_context():
        trasa, order = _na_trasie('robocza', statusy=('czeka_na_pakowanie',))
        for p in order.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()
        routes.usun_przystanek(trasa, order.id)
        db.session.commit()
        with app.test_request_context():
            dane = serialize_order(order.products[0], station_code='packaging')
        assert dane['transport']['trip_name'] is None
        assert all(p.updated_at > datetime(2026, 1, 1) for p in order.products)


def test_lista_pokazuje_trase_i_filtr_bez_trasy(client, app):
    with app.app_context():
        trasa, order = _na_trasie('robocza', statusy=('czeka_na_wyciecie',))
        wolne = zamowienie(sposob=s.TRANSPORT)
        # id-ki jako Pythonowe liczby, PRZED wyjściem z app_context: `order`/`trasa`/`wolne`
        # są odłączone od sesji, gdy scoped session schodzi razem z kontekstem aplikacji
        # (ten sam wzorzec co tests/test_logistyka_geo_api.py) — dostęp do .id po wyjściu
        # rzuciłby DetachedInstanceError.
        tid, oid, wolne_id = trasa.id, order.id, wolne.id
    wiersze = {o['id']: o for o in client.get(BASE + '/orders').get_json()['orders']}
    assert wiersze[oid]['trasa'] == {'id': tid, 'nazwa': 'Kraków + Tarnów', 'status': 'robocza'}
    bez = client.get(BASE + '/orders?sposob=bez_trasy').get_json()['orders']
    assert [o['id'] for o in bez] == [wolne_id]


def test_cofniecie_zdejmuje_z_roboczej(app):
    """Review Focus 6 — „Nie ustawiono” (sposoby.BRAK) z etapu 2."""
    with app.app_context():
        _trasa, order = _na_trasie('robocza', statusy=('czeka_na_wyciecie',))
        wynik = delivery.ustaw_sposob_dostawy(order, s.BRAK)
        db.session.commit()
        assert wynik['usunieto_z_trasy'] == 'Kraków + Tarnów'
        assert order.override_delivery_method is None
        assert routes.przystanek_zamowienia(order.id) is None


def test_cofniecie_na_zatwierdzonej_to_409(app):
    with app.app_context():
        _trasa, order = _na_trasie('zatwierdzona', statusy=('czeka_na_wyciecie',))
        with pytest.raises(LogistykaBlad) as e:
            delivery.ustaw_sposob_dostawy(order, s.BRAK)
        assert e.value.status == 409 and 'cofnij' in e.value.komunikat


def test_zmiana_adresu_na_zatwierdzonej_to_409(app):
    """Review Focus 7."""
    with app.app_context():
        _trasa, order = _na_trasie('zatwierdzona', statusy=('czeka_na_wyciecie',))
        with pytest.raises(LogistykaBlad) as e:
            delivery.zmien_adres(order, 'Nowa 1', '30-001', 'Kraków')
        assert e.value.status == 409 and 'cofnij' in e.value.komunikat


def test_niezmieniony_adres_na_zatwierdzonej_to_false_bez_bledu(app):
    """R5: zapis okna adresu bez zmian na zatwierdzonej trasie to no-op, nie 409 —
    dopiero zmiana adresu na zatwierdzonej trasie wymaga cofnięcia zatwierdzenia."""
    with app.app_context():
        _trasa, order = _na_trasie('zatwierdzona', statusy=('czeka_na_wyciecie',))
        adres, kod, miasto = order.delivery_address, order.delivery_postcode, order.delivery_city
        assert delivery.zmien_adres(order, adres, kod, miasto) is False


def test_zmiana_adresu_na_roboczej_zostaje_na_trasie(app):
    with app.app_context():
        _trasa, order = _na_trasie('robocza', statusy=('czeka_na_wyciecie',))
        assert delivery.zmien_adres(order, 'Nowa 1', '30-001', 'Kraków') is True
        db.session.commit()
        assert routes.przystanek_zamowienia(order.id) is not None


def test_niezmieniony_sposob_ma_pelny_slownik(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER)
        assert delivery.ustaw_sposob_dostawy(order, s.KURIER) == {
            'zmieniono': False, 'przepakowanie': False, 'usunieto_z_trasy': None}


# ── Fix-1: pinezka mapy blokowana jak adres na trasie zatwierdzonej/wykonanej ────

def test_pin_na_zatwierdzonej_trasie_to_409(client, app):
    """Ręczna korekta i reset pinezki: ten sam gate co adres (delivery._przystanek_do_zmiany
    przez publiczne delivery.sprawdz_trase_przed_zmiana) — eksport do Routimo (spec 8.4)
    mógł już pójść z bieżącym punktem."""
    with app.app_context():
        _trasa, order = _na_trasie('zatwierdzona', statusy=('czeka_na_wyciecie',))
        db.session.add(OrderGeo(order_id=order.id, lat=50.0, lng=20.0, source='reczna',
                                quality='dokladna', address_hash='x' * 40))
        db.session.commit()
        oid = order.id
    r = client.put(BASE + '/orders/%d/geo' % oid, json={'lat': 51.0, 'lng': 21.0})
    assert r.status_code == 409 and 'cofnij' in r.get_json()['error']
    r2 = client.post(BASE + '/orders/%d/geo/reset' % oid)
    assert r2.status_code == 409 and 'cofnij' in r2.get_json()['error']
    with app.app_context():
        punkt = OrderGeo.query.get(oid)
        assert punkt is not None
        assert (float(punkt.lat), float(punkt.lng)) == (50.0, 20.0)


def test_pin_na_wykonanej_trasie_to_409(client, app):
    with app.app_context():
        _trasa, order = _na_trasie('wykonana', statusy=('spakowane',))
        oid = order.id
    assert client.put(BASE + '/orders/%d/geo' % oid,
                      json={'lat': 51.0, 'lng': 21.0}).status_code == 409
    assert client.post(BASE + '/orders/%d/geo/reset' % oid).status_code == 409


def test_pin_na_roboczej_trasie_dziala(client, app):
    with app.app_context():
        _trasa, order = _na_trasie('robocza', statusy=('czeka_na_wyciecie',))
        oid = order.id
    assert client.put(BASE + '/orders/%d/geo' % oid,
                      json={'lat': 51.0, 'lng': 21.0}).status_code == 200
    assert client.post(BASE + '/orders/%d/geo/reset' % oid).status_code == 200
