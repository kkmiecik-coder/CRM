# -*- coding: utf-8 -*-
"""
Przystanek daleko od drogi na mapie (runda poprawek po przeglądzie końcowym, decyzja Konrada 4.10).

Prawdziwy ORS (sprawdzone 4.10): Snap i Directions (`radiuses: -1`) przyciągają punkt do ok. 3 km od drogi,
dalej Directions odpowiada 404 (kod 2010) dla CAŁEJ trasy. Trasa ma iść po drogach do najbliższego punktu na drodze
(„punkt do odbicia”), a od niego do pinezki — odcinek prosty (przerywany na mapie).
"""
import json
from datetime import datetime

import pytest
import requests

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import geocoding, routes, routing
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401

M = geocoding.MAGAZYN
BLISKO = (49.85, 22.40)
LAS = (49.0905, 22.5650)
GODZINA = datetime(2026, 10, 4, 10, 15)


class Odp(object):
    def __init__(self, dane, status=200):
        self.dane, self.status_code = dane, status
        self.text = json.dumps(dane)

    def json(self):
        return self.dane

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)


BLAD_2010 = {'error': {'code': 2010, 'message': 'Could not find routable point within the maximum possible radius '
                                                'of 350.0 meters of specified coordinate 2: 22.5650000 49.0905000.'}}


class FakeOrs(object):
    """
    ORS bez sieci: wokół każdego punktu z `pustkowia` ({(lat, lng): promień km}) nie ma dróg, poza nimi droga jest
    wszędzie (Snap zwraca ten sam punkt). Directions: 404 kod 2010, gdy któryś punkt leży w pustkowiu (albo kolejny
    status z `statusy_dir`), inaczej km = suma odcinków prostych, minuty = km.
    """

    def __init__(self, pustkowia=None, statusy_dir=(), status_snap=200, przyciagniecia=None):
        self.pustkowia = dict(pustkowia or {})
        # (M5) Pinezka w pasie ok. 3 km: Directions jej nie przyciąga (404/2010), Snap — tak, do podanego punktu.
        self.przyciagniecia = dict(przyciagniecia or {})
        self.statusy_dir, self.status_snap = list(statusy_dir), status_snap
        self.przebiegi, self.snapy, self.timeouty = [], [], []

    def _w_pustkowiu(self, p):
        return any(routing.odleglosc_km(p, c) < r for c, r in self.pustkowia.items())

    def __call__(self, url, json=None, headers=None, timeout=None):
        assert headers['Authorization'] == 'klucz' and timeout is not None
        self.timeouty.append((url, timeout))
        if url == routing.ORS_SNAP_URL:
            self.snapy.append(json)
            if self.status_snap != 200:
                return Odp({'error': 'x'}, self.status_snap)
            def miejsce(c):
                p = (c[1], c[0])
                if p in self.przyciagniecia:
                    d = self.przyciagniecia[p]
                    return {'location': [d[1], d[0]], 'snapped_distance': 3000.0}
                if self._w_pustkowiu(p):
                    return None
                return {'location': [c[0], c[1]], 'snapped_distance': 0.0}
            return Odp({'locations': [miejsce(c) for c in json['locations']]})
        assert url == routing.ORS_URL
        self.przebiegi.append(json['coordinates'])
        assert json['radiuses'] == [-1] * len(json['coordinates'])
        punkty = [(c[1], c[0]) for c in json['coordinates']]
        if self.statusy_dir:
            status = self.statusy_dir.pop(0)
            if status != 200:
                return Odp(BLAD_2010 if status == 404 else {'error': 'x'}, status)
        elif any(self._w_pustkowiu(p) or p in self.przyciagniecia for p in punkty):
            return Odp(BLAD_2010, 404)
        km = sum(routing.odleglosc_km(a, b) for a, b in zip(punkty, punkty[1:]))
        return Odp({'features': [{'geometry': {'type': 'LineString', 'coordinates': json['coordinates']},
                                  'properties': {'summary': {'distance': km * 1000.0, 'duration': km * 60.0}}}]})


@pytest.fixture(autouse=True)
def klucz(app):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    yield
    app.config.pop('OPENROUTESERVICE_API_KEY', None)


def _trasa(*punkty):
    trasa = routes.utworz({'name': 'Bieszczady', 'date_from': '2026-10-04'})
    zamowienia = [zamowienie(sposob=s.TRANSPORT) for _ in punkty]
    routes.dodaj_przystanki(trasa, [o.id for o in zamowienia])
    for order, p in zip(zamowienia, punkty):
        db.session.add(OrderGeo(order_id=order.id, lat=p[0], lng=p[1], source='reczna',
                                quality='dokladna', address_hash='x' * 40))
    db.session.commit()
    return trasa, geocoding.geo_zamowien([o.id for o in zamowienia]), zamowienia


def _lnglat(p):
    return [p[1], p[0]]


def test_przystanek_daleko_od_drogi_jedzie_po_drogach_do_punktu_odbicia(app):
    with app.app_context():
        trasa, punkty, zamowienia = _trasa(BLISKO, LAS)
        ors = FakeOrs(pustkowia={LAS: 4.5})
        assert routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA) is True
        # 1. Directions → 404/2010, 2. Snap przystanków (kto daleko), 3.–4. Snap kandydatów (zgrubnie, dokładnie),
        # 5. Directions z punktem na drodze w miejscu pinezki.
        assert [u for u, _ in ors.timeouty] == [routing.ORS_URL, routing.ORS_SNAP_URL, routing.ORS_SNAP_URL,
                                                routing.ORS_SNAP_URL, routing.ORS_URL]
        assert ors.snapy[0]['locations'] == [_lnglat(BLISKO), _lnglat(LAS)]
        droga = (ors.przebiegi[1][2][1], ors.przebiegi[1][2][0])
        # Najbliższy punkt na drodze: tuż za granicą pustkowia (zgrubnie co 3 km, potem co 1 km).
        assert 4.5 <= routing.odleglosc_km(LAS, droga) <= 5.7
        m = _lnglat((M['lat'], M['lng']))
        assert ors.przebiegi[1][0] == m and ors.przebiegi[1][1] == _lnglat(BLISKO) and ors.przebiegi[1][3] == m
        przebieg = routing.przebieg(trasa)
        assert przebieg['type'] == 'LineString' and przebieg['coordinates'] == ors.przebiegi[1]
        assert przebieg['odcinki_proste'] == [[_lnglat(droga), _lnglat(LAS)]]
        # Km: po drogach + odcinek prosty tam i z powrotem; czas — tylko po drogach.
        po_drogach = sum(routing.odleglosc_km((a[1], a[0]), (b[1], b[0]))
                         for a, b in zip(ors.przebiegi[1], ors.przebiegi[1][1:]))
        assert float(trasa.distance_km) == pytest.approx(po_drogach + 2 * routing.odleglosc_km(droga, LAS), abs=0.1)
        assert trasa.duration_min == int(round(po_drogach))
        assert trasa.geometry_approx is False
        # Cache: te same punkty — bez zapytań; pinezka nie ruszona.
        assert routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA) is False
        assert len(ors.timeouty) == 5
        geo = OrderGeo.query.get(zamowienia[1].id)
        assert (float(geo.lat), float(geo.lng), geo.source) == (LAS[0], LAS[1], 'reczna')


def test_podsumowanie_mowi_o_odcinkach_prostych(app):
    with app.app_context():
        trasa, punkty, zamowienia = _trasa(BLISKO, LAS)
        routing.przelicz(trasa, punkty, http_post=FakeOrs(pustkowia={LAS: 4.5}), teraz=GODZINA)
        p = routes.podsumowanie(trasa, zamowienia, punkty)
        assert p['przyblizony'] is False and p['odcinki_proste'] == 1
        trasa2, punkty2, zamowienia2 = _trasa(BLISKO)
        routing.przelicz(trasa2, punkty2, http_post=FakeOrs(), teraz=GODZINA)
        assert routes.podsumowanie(trasa2, zamowienia2, punkty2)['odcinki_proste'] == 0


def test_bez_drogi_w_zasiegu_szukania_cala_trasa_liniami_prostymi(app):
    with app.app_context():
        trasa, punkty, _ = _trasa(BLISKO, LAS)
        ors = FakeOrs(pustkowia={LAS: routing.MAKS_ODBICIA_KM + 10})
        assert routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA) is True
        assert trasa.geometry_approx is True and trasa.duration_min is None
        assert 'odcinki_proste' not in routing.przebieg(trasa)
        # Zgrubne szukanie nic nie znalazło — bez drugiego przejścia i bez drugiego Directions.
        assert len(ors.snapy) == 2 and len(ors.przebiegi) == 1
        # Jak przy awarii ORS: ponowna próba najwyżej raz na godzinę.
        assert routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA) is False


def test_drugi_directions_nieudany_to_linie_proste(app):
    with app.app_context():
        trasa, punkty, _ = _trasa(BLISKO, LAS)
        ors = FakeOrs(pustkowia={LAS: 4.5}, statusy_dir=[404, 500])
        routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA)
        assert len(ors.przebiegi) == 2 and trasa.geometry_approx is True


def test_zwykly_blad_directions_bez_szukania_drogi(app):
    with app.app_context():
        trasa, punkty, _ = _trasa(BLISKO, LAS)
        ors = FakeOrs(statusy_dir=[500])
        routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA)
        assert ors.snapy == [] and trasa.geometry_approx is True


def test_blad_snap_to_linie_proste(app):
    with app.app_context():
        trasa, punkty, _ = _trasa(BLISKO, LAS)
        ors = FakeOrs(pustkowia={LAS: 4.5}, status_snap=500)
        routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA)
        assert len(ors.snapy) == 1 and len(ors.przebiegi) == 1 and trasa.geometry_approx is True


def test_za_duzo_przystankow_daleko_od_drogi_bez_szukania(app):
    with app.app_context():
        dalekie = [(49.0905 + i * 0.3, 22.565) for i in range(routing.MAKS_DALEKICH + 1)]
        trasa, punkty, _ = _trasa(*dalekie)
        ors = FakeOrs(pustkowia={p: 4.5 for p in dalekie})
        routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA)
        assert len(ors.snapy) == 1 and trasa.geometry_approx is True


def test_dwa_przystanki_daleko_od_drogi_jednym_zapytaniem_kandydatow(app):
    with app.app_context():
        drugi = (49.40, 22.70)
        trasa, punkty, _ = _trasa(LAS, BLISKO, drugi)
        ors = FakeOrs(pustkowia={LAS: 4.5, drugi: 3.5})
        routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA)
        assert len(ors.snapy) == 3 and trasa.geometry_approx is False
        odcinki = routing.przebieg(trasa)['odcinki_proste']
        assert [o[1] for o in odcinki] == [_lnglat(LAS), _lnglat(drugi)]


def test_budzet_czasu_konczy_szukanie_liniami_prostymi(app):
    with app.app_context():
        trasa, punkty, _ = _trasa(BLISKO, LAS)
        chwile = iter([0.0, 0.0, 0.0, 0.0, 30.0])   # start, sprawdzenie, Directions, Snap przystanków, Snap kandydatów
        zegar = routing.Zegar(zrodlo=lambda: next(chwile))
        ors = FakeOrs(pustkowia={LAS: 4.5})
        routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA, zegar=zegar)
        assert len(ors.snapy) == 1 and trasa.geometry_approx is True


def test_kolejne_zapytania_dostaja_reszte_budzetu(app):
    with app.app_context():
        trasa, punkty, _ = _trasa(BLISKO, LAS)
        ors = FakeOrs(pustkowia={LAS: 4.5})
        routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA)
        assert ors.timeouty[0][1] == routing.TIMEOUT_S
        for _, timeout in ors.timeouty[1:]:
            assert timeout[0] == routing.TIMEOUT_S[0] and 0 < timeout[1] <= routing.TIMEOUT_S[1]


def test_szukaj_drogi_wybiera_najblizsza(app):
    """Droga tylko na wschód od pinezki (dalej niż 3 km) i daleko na zachodzie — wynik po wschodniej stronie."""
    p = (50.0, 20.0)

    def snap(lokalizacje):
        wynik = []
        for q in lokalizacje:
            dx = routing.odleglosc_km(p, (p[0], q[1])) * (1 if q[1] > p[1] else -1)
            wynik.append(q if dx >= 7.0 or dx <= -20.0 else None)
        return wynik

    drogi = routing.szukaj_drogi([p], snap)
    assert set(drogi) == {0}
    assert drogi[0][1] > p[1] and 7.0 <= routing.odleglosc_km(p, drogi[0]) <= 8.5


def test_szukaj_drogi_bez_drogi_pusty_wynik(app):
    assert routing.szukaj_drogi([(50.0, 20.0)], lambda lokalizacje: [None] * len(lokalizacje)) == {}


# ─── API i front ──────────────────────────────────────────────────────────────

def test_szczegoly_trasy_z_odcinkiem_prostym(client, app, monkeypatch):
    monkeypatch.setattr(routing.requests, 'post', FakeOrs(pustkowia={LAS: 4.5}))
    with app.app_context():
        trasa, _, _ = _trasa(BLISKO, LAS)
        trasa_id = trasa.id
    odp = client.get('/production/api/logistics/routes/%d' % trasa_id)
    assert odp.status_code == 200
    dane = odp.get_json()['route']
    assert dane['podsumowanie']['odcinki_proste'] == 1 and dane['podsumowanie']['przyblizony'] is False
    assert dane['przebieg']['odcinki_proste'][0][1] == _lnglat(LAS)
    mapa = client.get('/production/api/logistics/routes/map').get_json()['routes']
    assert [t['przebieg']['odcinki_proste'][0][1] for t in mapa if t['id'] == trasa_id] == [_lnglat(LAS)]


def _statyka(*czesci):
    import os
    katalog = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'modules', 'production', 'logistics')
    return open(os.path.join(katalog, *czesci), encoding='utf-8').read()


def test_front_rysuje_odcinek_prosty_przerywana():
    for plik in ('logistics-routes.js', 'logistics-map.js'):
        js = _statyka('static', 'js', plik)
        funkcja = js[js.index('function odcinkiProste('):]
        assert 'geo.odcinki_proste' in funkcja[:400], plik
        rysowanie = js[js.index('// Od punktu na drodze do pinezki'):]
        assert "dashArray: '8 8'" in rysowanie[:600] and 'is-przyblizona' in rysowanie[:600], plik
    trasy = _statyka('static', 'js', 'logistics-routes.js')
    assert "'Część trasy w linii prostej: przystanek daleko od drogi'" in trasy
    assert 'p.odcinki_proste' in trasy and 'w.odcinki_proste' in trasy
    assert 'Część trasy w linii prostej: przystanek daleko od drogi. ' in _statyka('static', 'js', 'logistics-map.js')


def test_wersje_skryptow_mapy_podbite():
    import re
    html = _statyka('templates', 'logistics', 'tab_content.html')
    for plik, stara in (('js/logistics-routes.js', '20261004a1'), ('js/logistics-map.js', '20261002u10')):
        m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
        assert m and m.group(1) > stara, plik


# ─── Dokładka po re-review rundy (M1, M5, M6) ─────────────────────────────────

def test_m1_bez_czasu_w_zadaniu_nie_pyta_ors_i_zostawia_cache(app):
    """Żądanie zużyło już budżet (np. czekało na blokadę) — przeliczenie odkładamy, cache bez zmian."""
    with app.app_context():
        trasa, punkty, _ = _trasa(BLISKO)
        zegar = routing.Zegar(budzet=routing.BUDZET_ZADANIA_S, start=0.0, zrodlo=lambda: 28.0)
        ors = FakeOrs()
        assert routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA, zegar=zegar) is False
        assert ors.timeouty == [] and trasa.geometry_hash is None


def test_m1_budzet_liczony_od_poczatku_zadania(client, app, monkeypatch):
    """Panel tras: zegar przeliczenia startuje na początku żądania (before_request blueprintu), nie w przelicz."""
    chwile = [100.0]   # start żądania, każdy kolejny odczyt — już po budżecie

    def zegar_systemowy():
        return chwile.pop(0) if chwile else 128.0

    monkeypatch.setattr(routing, '_monotoniczny', zegar_systemowy)
    ors = FakeOrs()
    monkeypatch.setattr(routing.requests, 'post', ors)
    with app.app_context():
        trasa, _, _ = _trasa(BLISKO)
        trasa_id = trasa.id
    odp = client.get('/production/api/logistics/routes/%d' % trasa_id)
    assert odp.status_code == 200 and ors.timeouty == []


def test_m1_w_budzecie_zadania_odczyt_skrocony_do_reszty(app):
    with app.app_context():
        trasa, punkty, _ = _trasa(BLISKO)
        zegar = routing.Zegar(budzet=routing.BUDZET_ZADANIA_S, start=0.0, zrodlo=lambda: 15.0)
        ors = FakeOrs()
        assert routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA, zegar=zegar) is True
        odczyt = ors.timeouty[0][1][1]
        assert odczyt == pytest.approx(routing.BUDZET_ZADANIA_S - 15.0 - routing.TIMEOUT_S[0])


def test_m5_punkt_w_pasie_przyciagniety_snapem_drugie_directions(app):
    """Directions 404/2010, a Snap przyciąga pinezkę (pas ok. 3 km) — drugie Directions z punktem ze Snap."""
    with app.app_context():
        pas = (49.30, 22.60)
        droga = (49.327, 22.60)
        trasa, punkty, _ = _trasa(BLISKO, pas)
        ors = FakeOrs(przyciagniecia={pas: droga})
        assert routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA) is True
        assert len(ors.przebiegi) == 2 and len(ors.snapy) == 1
        assert ors.przebiegi[1][2] == _lnglat(droga) and ors.przebiegi[1][1] == _lnglat(BLISKO)
        assert trasa.geometry_approx is False


def test_m6_ta_sama_daleka_pinezka_dwa_zamowienia_odcinek_raz(app):
    with app.app_context():
        trasa, punkty, _ = _trasa(BLISKO, LAS, LAS)
        ors = FakeOrs(pustkowia={LAS: 4.5})
        routing.przelicz(trasa, punkty, http_post=ors, teraz=GODZINA)
        assert trasa.geometry_approx is False
        odcinki = routing.przebieg(trasa)['odcinki_proste']
        assert len(odcinki) == 1
        droga = (odcinki[0][0][1], odcinki[0][0][0])
        po_drogach = sum(routing.odleglosc_km((a[1], a[0]), (b[1], b[0]))
                         for a, b in zip(ors.przebiegi[1], ors.przebiegi[1][1:]))
        assert float(trasa.distance_km) == pytest.approx(po_drogach + 2 * routing.odleglosc_km(droga, LAS), abs=0.1)
        # Kandydaci szukani raz dla jednej pinezki.
        assert len(ors.snapy[1]['locations']) == len(routing._okregi(LAS, routing.KROK_ZGRUBNY_KM,
                                                                     routing.MAKS_ODBICIA_KM,
                                                                     routing.KROK_ZGRUBNY_KM))
