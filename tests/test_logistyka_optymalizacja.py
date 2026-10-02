# -*- coding: utf-8 -*-
"""Krok 4.4d: optymalizacja kolejności przystanków trasy roboczej (services/optymalizacja.py, POST /optimize)."""
import pytest
import requests

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog, OrderGeo, Route
from modules.production.logistics.services import geocoding, optymalizacja, routes, routing
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401

M = geocoding.MAGAZYN
# Punkty na wschód od magazynu (Bachórz) w rosnącej odległości: BLISKO < SRODEK < DALEKO.
BLISKO = (49.85, 22.40)
SRODEK = (49.86, 22.80)
DALEKO = (49.87, 23.20)


class Odp(object):
    def __init__(self, dane, status=200):
        self.dane, self.status_code = dane, status

    def json(self):
        return self.dane

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)


class FakeOrs(object):
    """
    ORS w testach: Optimization zwraca `kolejnosc` (id zadań) i `nieprzydzielone`; Directions liczy km z linii
    prostych między podanymi punktami (km = suma odcinków, minuty = km) — lepsza kolejność daje mniej km.
    """

    def __init__(self, kolejnosc=None, nieprzydzielone=(), blad=None, status_opt=200, status_dir=200, dane_opt=None):
        self.kolejnosc, self.nieprzydzielone = kolejnosc, list(nieprzydzielone)
        self.blad, self.status_opt, self.status_dir, self.dane_opt = blad, status_opt, status_dir, dane_opt
        self.optymalizacje, self.przebiegi = [], []

    def __call__(self, url, json=None, headers=None, timeout=None):
        assert headers['Authorization'] == 'klucz' and timeout is not None
        if self.blad:
            raise self.blad
        if url == optymalizacja.ORS_OPTIMIZATION_URL:
            self.optymalizacje.append(json)
            if self.dane_opt is not None:
                return Odp(self.dane_opt, self.status_opt)
            kolejnosc = self.kolejnosc if self.kolejnosc is not None else [j['id'] for j in json['jobs']]
            kroki = ([{'type': 'start'}] + [{'type': 'job', 'job': i} for i in kolejnosc] + [{'type': 'end'}])
            return Odp({'code': 0, 'routes': [{'vehicle': 1, 'steps': kroki}],
                        'unassigned': [{'id': i} for i in self.nieprzydzielone]}, self.status_opt)
        assert url == routing.ORS_URL
        self.przebiegi.append(json['coordinates'])
        punkty = [(c[1], c[0]) for c in json['coordinates']]
        km = sum(routing.odleglosc_km(a, b) for a, b in zip(punkty, punkty[1:]))
        return Odp({'features': [{'geometry': {'type': 'LineString', 'coordinates': json['coordinates']},
                                  'properties': {'summary': {'distance': km * 1000.0, 'duration': km * 60.0}}}]},
                   self.status_dir)


@pytest.fixture(autouse=True)
def klucz(app):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    yield
    app.config.pop('OPENROUTESERVICE_API_KEY', None)


def _zamowienie(punkt=None, jakosc='dokladna', statusy=('czeka_na_wyciecie',)):
    order = zamowienie(sposob=s.TRANSPORT, statusy=statusy)
    if punkt is not None:
        db.session.add(OrderGeo(order_id=order.id, lat=punkt[0], lng=punkt[1], source='gugik',
                                quality=jakosc, address_hash='x' * 40))
        db.session.commit()
    return order.id


def _trasa(*order_ids):
    trasa = routes.utworz({'name': 'Rzeszów', 'date_from': '2026-10-01'})
    routes.dodaj_przystanki(trasa, list(order_ids))
    db.session.commit()
    return trasa


def _km(*punkty):
    p = [(M['lat'], M['lng'])] + list(punkty) + [(M['lat'], M['lng'])]
    return round(sum(routing.odleglosc_km(a, b) for a, b in zip(p, p[1:])), 1)


# ─── Serwis ────────────────────────────────────────────────────────────────

def test_proponuje_kolejnosc_z_ors_i_liczy_zysk(app):
    with app.app_context():
        d, b, sr = _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        trasa = _trasa(d, b, sr)
        ors = FakeOrs(kolejnosc=[b, sr, d])
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        cialo = ors.optymalizacje[0]
        assert cialo['vehicles'] == [{'id': 1, 'profile': 'driving-car', 'start': [M['lng'], M['lat']],
                                      'end': [M['lng'], M['lat']]}]
        assert cialo['jobs'] == [{'id': d, 'location': [DALEKO[1], DALEKO[0]]},
                                 {'id': b, 'location': [BLISKO[1], BLISKO[0]]},
                                 {'id': sr, 'location': [SRODEK[1], SRODEK[0]]}]
        assert wynik['obecne_order_ids'] == [d, b, sr]
        assert wynik['order_ids'] == [b, sr, d]
        assert wynik['zmieniona'] is True
        assert wynik['obecna']['km'] == pytest.approx(_km(DALEKO, BLISKO, SRODEK), abs=0.1)
        assert wynik['proponowana']['km'] == pytest.approx(_km(BLISKO, SRODEK, DALEKO), abs=0.1)
        assert wynik['zysk']['km'] == pytest.approx(wynik['obecna']['km'] - wynik['proponowana']['km'], abs=0.05)
        assert wynik['zysk']['km'] > 0 and wynik['zysk']['minuty'] > 0
        assert [(p['order_id'], p['pozycja_obecna'], p['pozycja_nowa'], p['optymalizowany'], p['powod'])
                for p in wynik['przystanki']] == [(b, 2, 1, True, None), (sr, 3, 2, True, None), (d, 1, 3, True, None)]
        assert wynik['przystanki'][0]['numer'].startswith('26/') and wynik['pominiete'] == 0
        assert len(ors.optymalizacje) == 1 and len(ors.przebiegi) == 2


def test_przystanki_bez_dokladnego_punktu_zostaja_na_koncu(app):
    with app.app_context():
        przybl = _zamowienie(SRODEK, jakosc='przyblizona')
        a = _zamowienie(DALEKO)
        bez = _zamowienie(None)
        anul = _zamowienie(BLISKO)
        b = _zamowienie(BLISKO)
        trasa = _trasa(przybl, a, bez, anul, b)
        # Anulowane w całości już na trasie (na trasę samo by nie weszło).
        for produkt in ProductionOrder.query.get(anul).products:
            produkt.current_status = 'anulowane'
        db.session.commit()
        ors = FakeOrs(kolejnosc=None)   # ORS nie zmienia kolejności zadań: a, b
        ors.kolejnosc = [b, a]
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        assert [j['id'] for j in ors.optymalizacje[0]['jobs']] == [a, b]
        assert wynik['order_ids'] == [b, a, przybl, bez, anul]
        assert {p['order_id']: p['powod'] for p in wynik['przystanki']} == {
            b: None, a: None, przybl: 'przyblizony', bez: 'brak_punktu', anul: 'anulowane'}
        assert wynik['pominiete'] == 3 and wynik['optymalizowane'] == 2
        # Przebieg (jak routing.py): przybliżony punkt jedzie, bez punktu i anulowane — nie.
        m = [M['lng'], M['lat']]
        assert ors.przebiegi[0] == [m, [SRODEK[1], SRODEK[0]], [DALEKO[1], DALEKO[0]], [BLISKO[1], BLISKO[0]], m]
        assert ors.przebiegi[1] == [m, [BLISKO[1], BLISKO[0]], [DALEKO[1], DALEKO[0]], [SRODEK[1], SRODEK[0]], m]


def test_mniej_niz_dwa_dokladne_to_nie_ma_czego_optymalizowac(app):
    with app.app_context():
        trasa = _trasa(_zamowienie(DALEKO), _zamowienie(SRODEK, jakosc='przyblizona'), _zamowienie(None))
        ors = FakeOrs()
        with pytest.raises(LogistykaBlad) as e:
            optymalizacja.zaproponuj(trasa, http_post=ors)
        assert e.value.status == 422 and e.value.komunikat.startswith(u'Nie ma czego optymalizować')
        assert e.value.dane == {'pominiete': 2}
        assert ors.optymalizacje == [] and ors.przebiegi == []


def test_brak_klucza_503(app):
    app.config.pop('OPENROUTESERVICE_API_KEY')
    with app.app_context():
        trasa = _trasa(_zamowienie(DALEKO), _zamowienie(BLISKO))
        ors = FakeOrs()
        with pytest.raises(LogistykaBlad) as e:
            optymalizacja.zaproponuj(trasa, http_post=ors)
        assert e.value.status == 503
        assert e.value.komunikat == u'Brak klucza OpenRouteService — optymalizacja niedostępna.'
        assert ors.optymalizacje == []


@pytest.mark.parametrize('ors, komunikat', [
    (FakeOrs(blad=requests.ConnectionError('brak sieci')), optymalizacja.KOMUNIKAT_BLAD),
    (FakeOrs(status_opt=500), optymalizacja.KOMUNIKAT_BLAD),
    (FakeOrs(status_opt=429), optymalizacja.KOMUNIKAT_LIMIT),
    (FakeOrs(status_dir=429), optymalizacja.KOMUNIKAT_LIMIT),
    (FakeOrs(status_dir=500), optymalizacja.KOMUNIKAT_BLAD),
    (FakeOrs(dane_opt={'code': 3, 'error': 'x'}), optymalizacja.KOMUNIKAT_BLAD),
    (FakeOrs(dane_opt={'code': 0, 'routes': [{'steps': [{'type': 'job', 'job': 999999}]}]}),
     optymalizacja.KOMUNIKAT_BLAD),
])
def test_blad_ors_to_komunikat_bez_zmian(app, ors, komunikat):
    with app.app_context():
        a, b = _zamowienie(DALEKO), _zamowienie(BLISKO)
        trasa = _trasa(a, b)
        with pytest.raises(LogistykaBlad) as e:
            optymalizacja.zaproponuj(trasa, http_post=ors)
        assert e.value.status == 502 and e.value.komunikat == komunikat
        assert [st.order_id for st in trasa.stops] == [a, b]


def test_nieosiagalne_zadanie_zostaje_na_koncu(app):
    with app.app_context():
        a, b, c = _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        trasa = _trasa(a, b, c)
        wynik = optymalizacja.zaproponuj(trasa, http_post=FakeOrs(kolejnosc=[c, b], nieprzydzielone=[a]))
        assert wynik['order_ids'] == [c, b, a]
        assert wynik['przystanki'][-1]['powod'] == 'nieosiagalny' and wynik['pominiete'] == 1


def test_ta_sama_kolejnosc_bez_drugiego_przebiegu(app):
    with app.app_context():
        a, b = _zamowienie(BLISKO), _zamowienie(DALEKO)
        trasa = _trasa(a, b)
        ors = FakeOrs(kolejnosc=[a, b])
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        assert wynik['zmieniona'] is False and wynik['zysk'] == {'km': 0.0, 'minuty': 0}
        assert len(ors.przebiegi) == 1


def test_obecny_przebieg_z_zapisanej_trasy(app):
    """Zapisany przebieg po drogach dla tych samych punktów — bez ponownego zapytania o obecną kolejność."""
    with app.app_context():
        a, b, c = _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        trasa = _trasa(a, b, c)
        assert routing.przelicz(trasa, geocoding.geo_zamowien([a, b, c]), http_post=FakeOrs()) is True
        db.session.commit()
        trasa.distance_km, trasa.duration_min = 999.9, 999   # znacznik: wartości z bazy, nie z ORS
        db.session.commit()
        ors = FakeOrs(kolejnosc=[b, c, a])
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        assert wynik['obecna'] == {'km': 999.9, 'minuty': 999}
        assert len(ors.przebiegi) == 1


def test_budzet_czasu_przerywa_przed_kolejnym_zapytaniem(app):
    with app.app_context():
        trasa = _trasa(_zamowienie(DALEKO), _zamowienie(BLISKO))
        chwile = iter([0.0, 0.0, 30.0])
        zegar = optymalizacja._Zegar(zrodlo=lambda: next(chwile))
        ors = FakeOrs()
        with pytest.raises(LogistykaBlad) as e:
            optymalizacja.zaproponuj(trasa, http_post=ors, zegar=zegar)
        assert e.value.status == 502 and len(ors.optymalizacje) == 1 and ors.przebiegi == []


def test_tylko_trasa_robocza(app):
    with app.app_context():
        trasa = _trasa(_zamowienie(DALEKO), _zamowienie(BLISKO))
        routes.zatwierdz(trasa)
        db.session.commit()
        with pytest.raises(LogistykaBlad) as e:
            optymalizacja.zaproponuj(trasa, http_post=FakeOrs())
        assert e.value.status == 409 and u'zatwierdzona' in e.value.komunikat


# ─── PUT /stops/order: zmieniona trasa → 409 ──────────────────────────────

def test_zmien_kolejnosc_inne_przystanki_409_powtorzenie_422(app):
    with app.app_context():
        a, b, c = _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        trasa = _trasa(a, b)
        with pytest.raises(LogistykaBlad) as e:
            routes.zmien_kolejnosc(trasa, [b, a, c])
        assert e.value.status == 409
        with pytest.raises(LogistykaBlad) as e:
            routes.zmien_kolejnosc(trasa, [b])
        assert e.value.status == 409
        with pytest.raises(LogistykaBlad) as e:
            routes.zmien_kolejnosc(trasa, [a, a])
        assert e.value.status == 422
        with pytest.raises(LogistykaBlad) as e:
            routes.zmien_kolejnosc(trasa, [b, a], oczekiwane=[b, a])
        assert e.value.status == 409
        db.session.rollback()
        routes.zmien_kolejnosc(trasa, [b, a], oczekiwane=[a, b])
        db.session.commit()
        assert [st.order_id for st in trasa.stops] == [b, a]


# ─── Endpoint ─────────────────────────────────────────────────────────────

def _podpnij(monkeypatch, ors):
    monkeypatch.setattr(optymalizacja.requests, 'post', ors)


def _stan_bazy(trasa_id):
    trasa = Route.query.get(trasa_id)
    return ([(st.order_id, st.position) for st in trasa.stops], trasa.geometry_hash, trasa.distance_km,
            LogisticsLog.query.count())


def test_endpoint_podglad_nic_nie_zapisuje(client, app, monkeypatch):
    with app.app_context():
        d, b, sr = _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        rid = _trasa(d, b, sr).id
        przed = _stan_bazy(rid)
    _podpnij(monkeypatch, FakeOrs(kolejnosc=[b, sr, d]))
    r = client.post(BASE + '/routes/%d/optimize' % rid)
    assert r.status_code == 200
    wynik = r.get_json()['optymalizacja']
    assert wynik['order_ids'] == [b, sr, d] and wynik['obecne_order_ids'] == [d, b, sr]
    assert set(wynik) >= {'route_id', 'zmieniona', 'obecna', 'proponowana', 'zysk', 'przystanki', 'pominiete'}
    with app.app_context():
        db.session.expire_all()
        assert _stan_bazy(rid) == przed
    # Zastosowanie istniejącym PUT z odpowiedzi podglądu.
    r = client.put(BASE + '/routes/%d/stops/order' % rid,
                   json={'order_ids': wynik['order_ids'], 'obecne_order_ids': wynik['obecne_order_ids']})
    assert r.status_code == 200
    assert [p['zamowienie']['id'] for p in r.get_json()['route']['przystanki']] == [b, sr, d]


def test_endpoint_zastosuj_po_zmianie_trasy_409(client, app, monkeypatch):
    with app.app_context():
        a, b, c = _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        rid = _trasa(a, b, c).id
    _podpnij(monkeypatch, FakeOrs(kolejnosc=[b, c, a]))
    wynik = client.post(BASE + '/routes/%d/optimize' % rid).get_json()['optymalizacja']
    # Ktoś w międzyczasie przestawił przystanki.
    assert client.put(BASE + '/routes/%d/stops/order' % rid, json={'order_ids': [c, a, b]}).status_code == 200
    r = client.put(BASE + '/routes/%d/stops/order' % rid,
                   json={'order_ids': wynik['order_ids'], 'obecne_order_ids': wynik['obecne_order_ids']})
    assert r.status_code == 409 and u'zmieniły się w międzyczasie' in r.get_json()['error']
    # …albo zdjął przystanek.
    assert client.delete(BASE + '/routes/%d/stops/%d' % (rid, c)).status_code == 200
    r = client.put(BASE + '/routes/%d/stops/order' % rid, json={'order_ids': wynik['order_ids']})
    assert r.status_code == 409


def test_endpoint_odmowy(client, app, monkeypatch):
    with app.app_context():
        rid = _trasa(_zamowienie(DALEKO), _zamowienie(BLISKO)).id
        jedna = _trasa(_zamowienie(SRODEK)).id
    _podpnij(monkeypatch, FakeOrs(status_opt=429))
    r = client.post(BASE + '/routes/%d/optimize' % rid)
    assert r.status_code == 502 and r.get_json() == {'success': False, 'error': optymalizacja.KOMUNIKAT_LIMIT}
    r = client.post(BASE + '/routes/%d/optimize' % jedna)
    assert r.status_code == 422 and r.get_json()['error'].startswith(u'Nie ma czego optymalizować')
    assert client.post(BASE + '/routes/999999/optimize').status_code == 404
    app.config.pop('OPENROUTESERVICE_API_KEY')
    r = client.post(BASE + '/routes/%d/optimize' % rid)
    assert r.status_code == 503 and 'Brak klucza OpenRouteService' in r.get_json()['error']
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    assert client.post(BASE + '/routes/%d/approve' % rid).status_code == 200
    r = client.post(BASE + '/routes/%d/optimize' % rid)
    assert r.status_code == 409 and u'zatwierdzona' in r.get_json()['error']


# ─── Front ────────────────────────────────────────────────────────────────

def test_przycisk_tylko_z_kluczem(client, app):
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    assert 'data-ors="1"' in html and 'data-lg="trasa-optymalizuj-dialog"' in html
    app.config.pop('OPENROUTESERVICE_API_KEY')
    assert 'data-ors="0"' in client.get(BASE + '/tab-content').get_data(as_text=True)


def test_front_optymalizacji():
    import os
    katalog = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'modules', 'production', 'logistics', 'static')
    js = open(os.path.join(katalog, 'js', 'logistics-routes.js'), encoding='utf-8').read()
    css = open(os.path.join(katalog, 'css', 'logistics-trasy.css'), encoding='utf-8').read()
    for fraza in ("'/optimize'", 'obecne_order_ids', "'Optymalizuj trasę'", 'ORS_DOSTEPNY', 'Zastosuj',
                  'Nie ma czego optymalizować'):
        assert fraza in js, fraza
    # Przycisk tylko w akcjach trasy roboczej.
    akcje = js[js.index('const AKCJE = {'):js.index('const bezRuchu')]
    assert akcje.count("'optymalizuj'") == 1
    assert akcje.index("'optymalizuj'") < akcje.index('zatwierdzona: [')
    ruch = css[css.index('@media (prefers-reduced-motion: reduce)'):]
    assert '.lg-optym-lista { transition: none; }' in ruch
