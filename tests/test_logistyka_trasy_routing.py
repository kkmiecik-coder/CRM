# -*- coding: utf-8 -*-
import json

import pytest
import requests

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import geocoding, routes, routing
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

ORS_ODP = {'type': 'FeatureCollection', 'features': [{
    'geometry': {'type': 'LineString', 'coordinates': [[22.25, 49.84], [19.94, 50.06], [22.25, 49.84]]},
    'properties': {'summary': {'distance': 412345.6, 'duration': 18000.0}}}]}


class Odp(object):
    def __init__(self, dane, status=200):
        self.dane, self.status_code = dane, status

    def json(self):
        return self.dane

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakePost(object):
    def __init__(self, odp=None, wyjatek=None):
        self.odp, self.wyjatek, self.wywolania = odp, wyjatek, []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.wywolania.append((url, json, headers, timeout))
        if self.wyjatek:
            raise self.wyjatek
        return self.odp


def _trasa_z_punktem(app, z_punktem=True):
    trasa = routes.utworz({'name': 'T', 'date_from': '2026-10-01'})
    order = zamowienie(sposob=s.TRANSPORT)
    routes.dodaj_przystanki(trasa, [order.id])
    if z_punktem:
        db.session.add(OrderGeo(order_id=order.id, lat=50.06, lng=19.94, source='gugik',
                                quality='dokladna', address_hash='x' * 40))
    db.session.commit()
    return trasa, geocoding.geo_zamowien([order.id])


def test_ors_liczy_przebieg_magazyn_przystanki_magazyn(app):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        http = FakePost(Odp(ORS_ODP))
        assert routing.przelicz(trasa, punkty, http_post=http) is True
        url, cialo, naglowki, timeout = http.wywolania[0]
        m = geocoding.MAGAZYN
        assert cialo['coordinates'] == [[m['lng'], m['lat']], [19.94, 50.06], [m['lng'], m['lat']]]
        assert naglowki['Authorization'] == 'klucz' and timeout == routing.TIMEOUT_S
        assert (float(trasa.distance_km), trasa.duration_min, trasa.geometry_approx) == (412.3, 300, False)
        assert routing.przebieg(trasa)['type'] == 'LineString'
        # Ten sam układ — bez ponownego zapytania.
        assert routing.przelicz(trasa, punkty, http_post=http) is False
        assert len(http.wywolania) == 1


def test_brak_klucza_to_linie_proste(app):
    """Review Focus 4."""
    app.config.pop('OPENROUTESERVICE_API_KEY', None)
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        http = FakePost(Odp(ORS_ODP))
        routing.przelicz(trasa, punkty, http_post=http)
        assert http.wywolania == []
        assert trasa.geometry_approx is True and trasa.duration_min is None
        assert float(trasa.distance_km) == pytest.approx(
            2 * routing.odleglosc_km((49.840438, 22.254053), (50.06, 19.94)), abs=0.1)


def test_blad_ors_to_linie_proste(app):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        routing.przelicz(trasa, punkty, http_post=FakePost(wyjatek=requests.Timeout('x')))
        assert trasa.geometry_approx is True


def test_przystanek_bez_wspolrzednych(app):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app, z_punktem=False)
        http = FakePost(Odp(ORS_ODP))
        routing.przelicz(trasa, punkty, http_post=http)
        assert http.wywolania == [] and trasa.geometry_approx is True


def test_pusta_trasa_czysci_przebieg(app):
    with app.app_context():
        trasa = routes.utworz({'name': 'Pusta', 'date_from': '2026-10-01'})
        trasa.geometry_json, trasa.distance_km = json.dumps({'type': 'LineString'}), 10
        routing.przelicz(trasa, {}, http_post=FakePost())
        assert trasa.geometry_json is None and trasa.distance_km is None
