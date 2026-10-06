# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta

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


def test_brak_klucza_loguje_warning_tylko_raz(app, monkeypatch, caplog):
    """Review Focus 5: brak klucza emituje WARNING najwyzej raz na proces."""
    app.config.pop('OPENROUTESERVICE_API_KEY', None)
    # Resetuj flage modulu do stanu poczatkowego
    monkeypatch.setattr(routing, '_klucz_ors_ostrzezono', False)
    with app.app_context():
        trasa1, punkty1 = _trasa_z_punktem(app)
        trasa2, punkty2 = _trasa_z_punktem(app)
        with caplog.at_level('WARNING'):
            routing.przelicz(trasa1, punkty1, http_post=FakePost())
            routing.przelicz(trasa2, punkty2, http_post=FakePost())
        warnings = [r for r in caplog.records if 'OPENROUTESERVICE_API_KEY' in r.message]
        assert len(warnings) == 1
        assert 'Brak OPENROUTESERVICE_API_KEY w config/core.json' in warnings[0].message


# ═══ Fala poprawek: I2 (skrót przebiegu wg przyczyny linii prostych), M12 ═══

GODZINA = datetime(2026, 10, 1, 10, 15)


def _trasa_z_punktami(n, bez_punktu=0):
    """Trasa z `n` przystankami, z czego `bez_punktu` ostatnich bez współrzędnych."""
    trasa = routes.utworz({'name': 'T%d' % n, 'date_from': '2026-10-01'})
    zamowienia = [zamowienie(sposob=s.TRANSPORT) for _ in range(n)]
    routes.dodaj_przystanki(trasa, [o.id for o in zamowienia])
    for i, order in enumerate(zamowienia[:n - bez_punktu]):
        db.session.add(OrderGeo(order_id=order.id, lat=50.0 + i * 0.01, lng=20.0 + i * 0.01,
                                source='gugik', quality='dokladna', address_hash='x' * 40))
    db.session.commit()
    return trasa, geocoding.geo_zamowien([o.id for o in zamowienia])


def test_ors_dostaje_radiuses_i_timeout_polaczenia(app):
    """M12: radiuses -1 (najbliższa droga bez limitu 350 m), timeout (połączenie, odczyt)."""
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        http = FakePost(Odp(ORS_ODP))
        routing.przelicz(trasa, punkty, http_post=http)
        _url, cialo, _naglowki, timeout = http.wywolania[0]
        assert cialo['radiuses'] == [-1, -1, -1]
        assert timeout == (3.05, 8)


def test_brak_klucza_a_potem_klucz_przelicza_po_drogach(app):
    """I2: bez klucza zapisany skrót „bez klucza” — gdy klucz się pojawi, trasa liczy się po
    drogach od razu (dawniej zostawała „przybliżona”, dopóki nie zmieniły się przystanki)."""
    app.config.pop('OPENROUTESERVICE_API_KEY', None)
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        assert routing.przelicz(trasa, punkty, http_post=FakePost()) is True
        assert trasa.geometry_approx is True
        assert routing.przelicz(trasa, punkty, http_post=FakePost()) is False   # bez klucza — bez zmian
        app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
        http = FakePost(Odp(ORS_ODP))
        assert routing.przelicz(trasa, punkty, http_post=http) is True
        assert len(http.wywolania) == 1 and trasa.geometry_approx is False
        assert routing.przelicz(trasa, punkty, http_post=http) is False
        # Klucz zniknął — dokładny przebieg zostaje (droga się nie zmieniła).
        app.config.pop('OPENROUTESERVICE_API_KEY', None)
        assert routing.przelicz(trasa, punkty, http_post=http) is False
        assert trasa.geometry_approx is False


def test_blad_ors_ponawia_najwyzej_raz_na_godzine(app):
    """I2: po błędzie ORS skrót z godziną błędu — w tej samej godzinie bez ponowienia (awaria
    nie kosztuje 8 s na każdym otwarciu trasy), godzinę później ponowienie i dokładny przebieg."""
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        awaria = FakePost(wyjatek=requests.ConnectionError('503'))
        assert routing.przelicz(trasa, punkty, http_post=awaria, teraz=GODZINA) is True
        assert trasa.geometry_approx is True and len(awaria.wywolania) == 1
        assert routing.przelicz(trasa, punkty, http_post=awaria,
                                teraz=GODZINA + timedelta(minutes=40)) is False
        assert len(awaria.wywolania) == 1
        http = FakePost(Odp(ORS_ODP))
        assert routing.przelicz(trasa, punkty, http_post=http, teraz=GODZINA + timedelta(hours=1)) is True
        assert len(http.wywolania) == 1 and trasa.geometry_approx is False
        assert float(trasa.distance_km) == 412.3


def test_ponad_48_przystankow_od_razu_linie_proste(app):
    """I2 + odłożone 104: > 48 przystanków — linie proste bez pytania ORS (limit 50 punktów),
    zwykły skrót: pojawienie się klucza niczego nie zmienia, póki punkty są te same."""
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktami(routing.MAKS_PRZYSTANKOW + 1)
        http = FakePost(Odp(ORS_ODP))
        assert routing.przelicz(trasa, punkty, http_post=http) is True
        assert http.wywolania == [] and trasa.geometry_approx is True
        assert len(routing.przebieg(trasa)['coordinates']) == routing.MAKS_PRZYSTANKOW + 3
        assert routing.przelicz(trasa, punkty, http_post=http) is False


def test_48_przystankow_jeszcze_po_drogach(app):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktami(routing.MAKS_PRZYSTANKOW)
        http = FakePost(Odp(ORS_ODP))
        routing.przelicz(trasa, punkty, http_post=http)
        assert len(http.wywolania) == 1 and len(http.wywolania[0][1]['coordinates']) == 50


def test_czesciowy_brak_wspolrzednych(app):
    """Odłożone 104: jeden przystanek bez punktu — linie proste przez znane punkty, bez ORS;
    skrót strukturalny (klucz niczego nie zmienia), ale uzupełniony punkt przelicza trasę."""
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktami(3, bez_punktu=1)
        http = FakePost(Odp(ORS_ODP))
        assert routing.przelicz(trasa, punkty, http_post=http) is True
        assert http.wywolania == [] and trasa.geometry_approx is True
        assert len(routing.przebieg(trasa)['coordinates']) == 4      # magazyn, 2 punkty, magazyn
        assert routing.przelicz(trasa, punkty, http_post=http) is False
        brakujacy = [s_.order_id for s_ in trasa.stops if s_.order_id not in punkty][0]
        db.session.add(OrderGeo(order_id=brakujacy, lat=50.5, lng=20.5, source='reczna',
                                quality='dokladna', address_hash='x' * 40))
        db.session.commit()
        punkty = geocoding.geo_zamowien([s_.order_id for s_ in trasa.stops])
        assert routing.przelicz(trasa, punkty, http_post=http) is True
        assert len(http.wywolania) == 1 and trasa.geometry_approx is False


def test_wymus_przelicza_mimo_aktualnego_skrotu(app):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        http = FakePost(Odp(ORS_ODP))
        routing.przelicz(trasa, punkty, http_post=http)
        assert routing.przelicz(trasa, punkty, http_post=http) is False
        assert routing.przelicz(trasa, punkty, http_post=http, wymus=True) is True
        assert len(http.wywolania) == 2


def test_anulowany_przystanek_poza_przebiegiem(app):
    """I5: zamówienie anulowane w całości nie wydłuża przebiegu (kierowca tam nie jedzie)."""
    app.config.pop('OPENROUTESERVICE_API_KEY', None)
    with app.app_context():
        trasa, punkty = _trasa_z_punktami(3)
        routing.przelicz(trasa, punkty, http_post=FakePost())
        assert len(routing.przebieg(trasa)['coordinates']) == 5
        drugi = routes.zamowienia_trasy(trasa)[1]
        for p in drugi.products:
            p.current_status = 'anulowane'
        db.session.commit()
        assert routing.przelicz(trasa, punkty, http_post=FakePost()) is True
        assert len(routing.przebieg(trasa)['coordinates']) == 4


def test_z_kluczem_nie_loguje_warning_o_braku_klucza(app, monkeypatch, caplog):
    """Z kluczem present, brak warningow o braku klucza."""
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    monkeypatch.setattr(routing, '_klucz_ors_ostrzezono', False)
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        http = FakePost(Odp(ORS_ODP))
        with caplog.at_level('WARNING'):
            routing.przelicz(trasa, punkty, http_post=http)
        warnings = [r for r in caplog.records if 'OPENROUTESERVICE_API_KEY' in r.message]
        assert len(warnings) == 0
