# -*- coding: utf-8 -*-
"""Krok 4.4d: optymalizacja kolejności przystanków trasy roboczej (services/optymalizacja.py, POST /optimize)."""
import json

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
# Punkt daleko od drogi (Bieszczady): prawdziwy ORS Snap zwraca dla niego null, a Optimization 500.
LAS = (49.0905, 22.5650)


class Odp(object):
    def __init__(self, dane, status=200):
        self.dane, self.status_code = dane, status
        self.text = json.dumps(self.dane)

    def json(self):
        return self.dane

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)


class FakeOrs(object):
    """
    ORS w testach: Snap przyciąga punkty (przesunięte o `przesun` stopni długości, `None` dla punktów z `daleko`);
    Optimization zwraca `kolejnosc` (id zadań) i `nieprzydzielone`, a wcześniej kolejne `bledy_opt` [(status, dane)];
    Directions liczy km z linii prostych między podanymi punktami (km = suma odcinków, minuty = km) — lepsza
    kolejność daje mniej km. `krok` — jak opisać zadanie w krokach VROOM: 'job', 'id' albo 'oba'.
    """

    def __init__(self, kolejnosc=None, nieprzydzielone=(), blad=None, status_opt=200, status_dir=200, dane_opt=None,
                 daleko=(), przesun=0.0, status_snap=200, dane_snap=None, bledy_opt=(), krok='job',
                 pustkowie_km=40.0, dir_404=()):
        self.kolejnosc, self.nieprzydzielone = kolejnosc, list(nieprzydzielone)
        self.blad, self.status_opt, self.status_dir, self.dane_opt = blad, status_opt, status_dir, dane_opt
        self.daleko, self.przesun, self.status_snap, self.dane_snap = set(daleko), przesun, status_snap, dane_snap
        self.bledy_opt, self.krok, self.pustkowie_km = list(bledy_opt), krok, pustkowie_km
        # Pinezki, których Directions nie przyciąga (404/2010), choć Snap tak — pas ok. 3 km od drogi.
        self.dir_404 = set(dir_404)
        self.optymalizacje, self.przebiegi, self.snapy, self.timeouty = [], [], [], []

    def _bez_drogi(self, punkt):
        # Wokół punktów z `daleko` nie ma dróg w promieniu `pustkowie_km` (domyślnie dalej, niż routing szuka
        # punktu do odbicia) — Snap zwraca null także dla kandydatów szukania drogi.
        return punkt in self.daleko or any(routing.odleglosc_km(punkt, d) < self.pustkowie_km for d in self.daleko)

    def __call__(self, url, json=None, headers=None, timeout=None):
        assert headers['Authorization'] == 'klucz' and timeout is not None
        self.timeouty.append((url, timeout))
        if self.blad:
            raise self.blad
        if url == optymalizacja.ORS_SNAP_URL:
            self.snapy.append(json)
            if self.dane_snap is not None or self.status_snap != 200:
                return Odp(self.dane_snap or {'error': 'x'}, self.status_snap)
            return Odp({'locations': [None if self._bez_drogi((c[1], c[0]))
                                      else {'location': [c[0] + self.przesun, c[1]], 'snapped_distance': 12.5}
                                      for c in json['locations']]})
        if url == optymalizacja.ORS_OPTIMIZATION_URL:
            self.optymalizacje.append(json)
            if self.bledy_opt:
                status, dane = self.bledy_opt.pop(0)
                return Odp(dane, status)
            if self.dane_opt is not None:
                return Odp(self.dane_opt, self.status_opt)
            wyslane = [j['id'] for j in json['jobs']]
            kolejnosc = self.kolejnosc if self.kolejnosc is not None else wyslane
            kolejnosc = [i for i in kolejnosc if i in wyslane]
            opis = {'job': lambda i: {'job': i}, 'id': lambda i: {'id': i},
                    'oba': lambda i: {'id': i, 'job': i}}[self.krok]
            kroki = ([{'type': 'start'}] + [dict(opis(i), type='job') for i in kolejnosc] + [{'type': 'end'}])
            return Odp({'code': 0, 'routes': [{'vehicle': 1, 'steps': kroki}],
                        'unassigned': [{'id': i} for i in self.nieprzydzielone]}, self.status_opt)
        assert url == routing.ORS_URL
        self.przebiegi.append(json['coordinates'])
        punkty = [(c[1], c[0]) for c in json['coordinates']]
        if any(p in self.dir_404 for p in punkty):
            return Odp({'error': {'code': 2010, 'message': 'Could not find routable point'}}, 404)
        km = sum(routing.odleglosc_km(a, b) for a, b in zip(punkty, punkty[1:]))
        return Odp({'features': [{'geometry': {'type': 'LineString', 'coordinates': json['coordinates']},
                                  'properties': {'summary': {'distance': km * 1000.0, 'duration': km * 60.0}}}]},
                   self.status_dir)


@pytest.fixture(autouse=True)
def klucz(app, monkeypatch):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    # (I2) Każde zapytanie HTTP w tym pliku idzie do atrapy — także przeliczenie przebiegu w odpowiedziach
    # PUT/DELETE/approve (routing.przelicz); testy podmieniające ORS nadpisują ją przez _podpnij.
    _podpnij(monkeypatch, FakeOrs())
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
        assert ors.snapy[0]['locations'] == [_lokalizacja(SRODEK), _lokalizacja(DALEKO), _lokalizacja(BLISKO)]
        assert wynik['poza_przebiegiem'] == 0
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
        chwile = iter([0.0, 0.0, 0.0, 30.0])   # start, Snap, Optimization, Directions
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


# ─── Przystanek daleko od drogi (I1 po przeglądzie 4.4d) ────────────────────

def _lokalizacja(punkt):
    return [punkt[1], punkt[0]]


def test_daleko_od_drogi_pominiety_przed_optymalizacja(app):
    """Snap zwraca null → przystanek nie idzie do VROOM, zostaje na końcu z powodem `daleko_od_drogi`;
    do VROOM i do km i czasu idą współrzędne przyciągnięte do drogi (Snap)."""
    with app.app_context():
        las, d, b, sr = _zamowienie(LAS), _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        trasa = _trasa(d, las, b, sr)
        ors = FakeOrs(kolejnosc=[b, sr, d], daleko=[LAS], przesun=0.001)
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        # Snap przystanków i (bez drogi w promieniu szukania) jedno zgrubne szukanie punktu do odbicia.
        assert len(ors.snapy) == 2
        assert ors.snapy[0]['locations'] == [_lokalizacja(DALEKO), _lokalizacja(LAS), _lokalizacja(BLISKO),
                                            _lokalizacja(SRODEK)]
        assert ors.snapy[0]['radius'] == optymalizacja.PROMIEN_SNAP_M
        assert [j['id'] for j in ors.optymalizacje[0]['jobs']] == [d, b, sr]
        assert ors.optymalizacje[0]['jobs'][0]['location'] == pytest.approx([DALEKO[1] + 0.001, DALEKO[0]])
        assert wynik['order_ids'] == [b, sr, d, las]
        assert wynik['przystanki'][-1]['powod'] == 'daleko_od_drogi'
        assert wynik['przystanki'][-1]['optymalizowany'] is False
        assert wynik['optymalizowane'] == 3 and wynik['pominiete'] == 1
        # Directions nie dojedzie tam, gdzie Snap nie znalazł drogi (prawdziwy ORS: 404 „routable point”) — km i czas
        # obu kolejności bez tego przystanku, a odpowiedź mówi, ilu przystanków nie liczymy.
        # Dokładka po re-review: km liczone na punktach ze Snap (tu przesuniętych o 0,001°).
        m = [M['lng'], M['lat']]

        def snap(p):
            return pytest.approx([p[1] + 0.001, p[0]])
        assert ors.przebiegi[0] == [m, snap(DALEKO), snap(BLISKO), snap(SRODEK), m]
        assert ors.przebiegi[1] == [m, snap(BLISKO), snap(SRODEK), snap(DALEKO), m]
        assert wynik['poza_przebiegiem'] == 1


def test_przyblizony_daleko_od_drogi_poza_przebiegiem(app):
    """Snap sprawdza też punkty przybliżone (do VROOM nie idą): bez drogi → `daleko_od_drogi`, poza km i czasem."""
    with app.app_context():
        przybl, a, b = _zamowienie(LAS, jakosc='przyblizona'), _zamowienie(DALEKO), _zamowienie(BLISKO)
        trasa = _trasa(przybl, a, b)
        ors = FakeOrs(kolejnosc=[b, a], daleko=[LAS])
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        assert ors.snapy[0]['locations'] == [_lokalizacja(LAS), _lokalizacja(DALEKO), _lokalizacja(BLISKO)]
        assert [j['id'] for j in ors.optymalizacje[0]['jobs']] == [a, b]
        assert wynik['order_ids'] == [b, a, przybl] and wynik['przystanki'][-1]['powod'] == 'daleko_od_drogi'
        assert all(_lokalizacja(LAS) not in przebieg for przebieg in ors.przebiegi)
        assert wynik['poza_przebiegiem'] == 1


def test_daleko_od_drogi_z_punktem_do_odbicia_optymalizowany(app):
    """
    Runda poprawek po przeglądzie końcowym (decyzja Konrada 4.10): przystanek dalej niż ok. 3 km od drogi, ale z drogą
    w promieniu szukania — do VROOM idzie punkt na drodze najbliższy pinezce (ten sam, co w przebiegu trasy), km
    obu kolejności: po drogach do tego punktu + odcinek prosty tam i z powrotem.
    """
    with app.app_context():
        las, d, b = _zamowienie(LAS), _zamowienie(DALEKO), _zamowienie(BLISKO)
        trasa = _trasa(las, d, b)
        ors = FakeOrs(kolejnosc=[b, las, d], daleko=[LAS], pustkowie_km=4.5)
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        assert len(ors.snapy) == 3   # przystanki, szukanie zgrubne i dokładne
        droga_vroom = [j['location'] for j in ors.optymalizacje[0]['jobs'] if j['id'] == las][0]
        droga = (droga_vroom[1], droga_vroom[0])
        assert 4.5 <= routing.odleglosc_km(LAS, droga) <= 5.7
        assert wynik['order_ids'] == [b, las, d]
        opis = [p for p in wynik['przystanki'] if p['order_id'] == las][0]
        assert opis['optymalizowany'] is True and opis['powod'] is None
        assert wynik['poza_przebiegiem'] == 0 and wynik['odcinki_proste'] == 1
        assert all(_lokalizacja(LAS) not in przebieg for przebieg in ors.przebiegi)
        assert [droga[1], droga[0]] in ors.przebiegi[1]
        prosty = 2 * routing.odleglosc_km(droga, LAS)
        assert wynik['proponowana']['km'] == pytest.approx(_km(BLISKO, droga, DALEKO) + prosty, abs=0.15)


def test_po_przyciagnieciu_jeden_przystanek_bez_optymalizacji(app):
    """Zostaje jeden przystanek przy drodze — VROOM nie ma czego układać, propozycja bez zapytania Optimization."""
    with app.app_context():
        las, b = _zamowienie(LAS), _zamowienie(BLISKO)
        trasa = _trasa(las, b)
        ors = FakeOrs(daleko=[LAS])
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        assert ors.optymalizacje == []
        assert wynik['order_ids'] == [b, las] and wynik['zmieniona'] is True
        assert wynik['optymalizowane'] == 1 and wynik['pominiete'] == 1


@pytest.mark.parametrize('blad', [
    {'code': 3, 'error': 'Unfound route(s) from location [23.200000,49.870000]'},
    {'error': {'code': 2010, 'message': 'Could not find routable point within a radius of 350.0 meters '
                                        'of specified coordinate 1: 23.2000000 49.8700000.'}},
    {'error': 'Could not find routable point within a radius of 350.0 meters of specified coordinate 1'},
])
def test_500_wskazujace_punkt_pomija_przystanek_i_ponawia_raz(app, blad):
    """Snap nie pomógł (np. sam nie odpowiedział), a Optimization wskazuje punkt — pomijamy go i ponawiamy raz.
    `coordinate N` liczy się w liście miejsc VROOM: magazyn (0), potem zadania (bez powtórzeń)."""
    with app.app_context():
        d, b, sr = _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        trasa = _trasa(d, b, sr)
        ors = FakeOrs(kolejnosc=[sr, b], status_snap=500, bledy_opt=[(500, blad)])
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        assert len(ors.optymalizacje) == 2
        assert [j['id'] for j in ors.optymalizacje[1]['jobs']] == [b, sr]
        assert wynik['order_ids'] == [sr, b, d]
        assert wynik['przystanki'][-1]['powod'] == 'daleko_od_drogi' and wynik['poza_przebiegiem'] == 1
        assert all(_lokalizacja(DALEKO) not in przebieg for przebieg in ors.przebiegi)


def test_drugi_blad_punktu_konczy_sie_502(app):
    with app.app_context():
        a, b, c = _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        trasa = _trasa(a, b, c)
        ors = FakeOrs(bledy_opt=[(500, {'code': 3, 'error': 'Unfound route(s) from location [23.200000,49.870000]'}),
                                 (500, {'code': 3, 'error': 'Unfound route(s) from location [22.400000,49.850000]'})])
        with pytest.raises(LogistykaBlad) as e:
            optymalizacja.zaproponuj(trasa, http_post=ors)
        assert e.value.status == 502 and len(ors.optymalizacje) == 2


def test_500_bez_wskazania_punktu_bez_ponowienia(app):
    with app.app_context():
        trasa = _trasa(_zamowienie(DALEKO), _zamowienie(BLISKO))
        ors = FakeOrs(bledy_opt=[(500, {'code': 3, 'error': 'Internal error'})])
        with pytest.raises(LogistykaBlad) as e:
            optymalizacja.zaproponuj(trasa, http_post=ors)
        assert e.value.status == 502 and e.value.komunikat == optymalizacja.KOMUNIKAT_BLAD
        assert len(ors.optymalizacje) == 1


@pytest.mark.parametrize('ors', [
    FakeOrs(status_snap=500),
    FakeOrs(status_snap=503),
    FakeOrs(dane_snap={'locations': [None]}),            # inna liczba punktów niż wysłana
    FakeOrs(dane_snap={'cos': 1}),
])
def test_blad_snap_optymalizuje_na_oryginalnych_punktach(app, ors):
    with app.app_context():
        a, b = _zamowienie(DALEKO), _zamowienie(BLISKO)
        trasa = _trasa(a, b)
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        assert ors.optymalizacje[0]['jobs'] == [{'id': a, 'location': _lokalizacja(DALEKO)},
                                                {'id': b, 'location': _lokalizacja(BLISKO)}]
        assert wynik['pominiete'] == 0


def test_limit_na_snap_to_komunikat_limitu(app):
    with app.app_context():
        trasa = _trasa(_zamowienie(DALEKO), _zamowienie(BLISKO))
        ors = FakeOrs(status_snap=429)
        with pytest.raises(LogistykaBlad) as e:
            optymalizacja.zaproponuj(trasa, http_post=ors)
        assert e.value.status == 502 and e.value.komunikat == optymalizacja.KOMUNIKAT_LIMIT
        assert ors.optymalizacje == []


@pytest.mark.parametrize('krok', ['job', 'id', 'oba'])
def test_kroki_vroom_z_job_albo_samym_id(app, krok):
    """(M2) VROOM opisuje zadanie w kroku polem `id` (każdy krok zadania) i `job` (tylko zadania)."""
    with app.app_context():
        d, b, sr = _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        trasa = _trasa(d, b, sr)
        wynik = optymalizacja.zaproponuj(trasa, http_post=FakeOrs(kolejnosc=[b, sr, d], krok=krok))
        assert wynik['order_ids'] == [b, sr, d]


def test_kolejne_zapytanie_dostaje_reszte_budzetu(app):
    """(M6) Odczyt kolejnego zapytania = reszta budżetu (bez czasu na połączenie), nie stałe MAKS_ODCZYT_S."""
    with app.app_context():
        d, b = _zamowienie(DALEKO), _zamowienie(BLISKO)
        trasa = _trasa(d, b)
        chwile = iter([0.0, 0.0, 1.0, 9.0, 15.0])   # start, Snap, Optimization, Directions obecna i proponowana
        zegar = optymalizacja._Zegar(zrodlo=lambda: next(chwile))
        ors = FakeOrs(kolejnosc=[b, d])
        optymalizacja.zaproponuj(trasa, http_post=ors, zegar=zegar)
        timeouty = [t for _, t in ors.timeouty]
        polaczenie = optymalizacja.POLACZENIE_S
        assert timeouty[0] == (polaczenie, optymalizacja.MAKS_SNAP_S)
        assert timeouty[1] == (polaczenie, optymalizacja.MAKS_ODCZYT_S)
        assert timeouty[2] == (polaczenie, pytest.approx(optymalizacja.BUDZET_S - 9.0 - polaczenie))
        assert timeouty[3] == (polaczenie, pytest.approx(optymalizacja.BUDZET_S - 15.0 - polaczenie))


# ─── I2: testy nie wychodzą do prawdziwego ORS ──────────────────────────────

def test_przelicz_bierze_requests_post_w_chwili_wolania(app, monkeypatch):
    """Domyślny HTTP w routing.przelicz to requests.post z chwili wołania (nie związany przy imporcie),
    więc podmiana w testach (np. _podpnij) obejmuje też przeliczenie po PUT/DELETE/approve."""
    with app.app_context():
        a, b = _zamowienie(DALEKO), _zamowienie(BLISKO)
        trasa = _trasa(a, b)
        ors = FakeOrs()
        _podpnij(monkeypatch, ors)
        assert routing.przelicz(trasa, geocoding.geo_zamowien([a, b])) is True
        assert len(ors.przebiegi) == 1 and trasa.geometry_approx is False


def test_odpowiedz_put_liczy_przebieg_na_atrapie(client, app, monkeypatch):
    with app.app_context():
        a, b = _zamowienie(DALEKO), _zamowienie(BLISKO)
        rid = _trasa(a, b).id
    ors = FakeOrs()
    _podpnij(monkeypatch, ors)
    assert client.put(BASE + '/routes/%d/stops/order' % rid, json={'order_ids': [b, a]}).status_code == 200
    assert len(ors.przebiegi) == 1


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


def _statyka(*czesci):
    import os
    katalog = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'modules', 'production', 'logistics')
    return open(os.path.join(katalog, *czesci), encoding='utf-8').read()


def _funkcja_js(js, nazwa):
    poczatek = js.index('function ' + nazwa + '(')
    return js[poczatek:js.index('\n    }\n', poczatek)]


def test_front_powod_daleko_od_drogi():
    js = _statyka('static', 'js', 'logistics-routes.js')
    powody = js[js.index('const POWODY_POMINIECIA = {'):]
    powody = powody[:powody.index('};')]
    assert "daleko_od_drogi: 'daleko od drogi'" in powody
    assert 'ustaw kolejność ręcznie albo popraw pinezkę' in js
    # Km i czas bez przystanków, do których ORS nie dojeżdża — okno to mówi.
    assert 'w.poza_przebiegiem' in js and 'bez ' in js
    # Akapit o pominiętych nie twierdzi już, że to tylko przystanki bez dokładnego punktu.
    assert 'bez dokładnego punktu (albo anulowanych)' not in js


def test_front_zastosuj_nie_glowny_gdy_propozycja_nie_skraca():
    """(M3) Zysk km ≤ 0: „Zastosuj” traci wygląd głównego przycisku, a werdykt mówi to wprost."""
    js = _statyka('static', 'js', 'logistics-routes.js')
    przyciski = _funkcja_js(js, 'odswiezPrzyciskiOptymalizacji')
    assert "classList.toggle('lg-przycisk--glowny', propozycjaSkraca(w))" in przyciski
    skraca = _funkcja_js(js, 'propozycjaSkraca')
    assert '(Number(w.zysk && w.zysk.km) || 0) > 0' in skraca and 'w.zmieniona' in skraca
    render = _funkcja_js(js, 'renderujOptymalizacje')
    assert 'Obecna kolejność jest już najlepsza' in render and 'propozycja nie skraca trasy' in render


def test_wersje_statykow_po_poprawkach_44d():
    """Wersje ?v= porównywane jako tekst: po v9 następna litera, nie v10."""
    import re
    html = _statyka('templates', 'logistics', 'tab_content.html')
    for plik, stara in (('js/logistics-routes.js', '20261002v1'), ('css/logistics-trasy.css', '20261002u10')):
        m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
        assert m and m.group(1) > stara, plik


def test_testy_logistyki_nie_lacza_sie_z_ors(app):
    """(I2) Strażnik w tests/logistyka_fixtures.py: zapytanie do ORS mimo atrap kończy się wyjątkiem, nie siecią."""
    from tests.logistyka_fixtures import OrsZablokowanyWTestach
    for url in (routing.ORS_URL, optymalizacja.ORS_OPTIMIZATION_URL, optymalizacja.ORS_SNAP_URL):
        with pytest.raises(OrsZablokowanyWTestach):
            requests.Session().post(url, json={}, timeout=1)


def test_m6_dwa_zamowienia_pod_ta_sama_daleka_pinezka_odcinek_raz(app):
    """(M6 po re-review) Kolejne przystanki pod tą samą daleką pinezką — odcinek prosty liczony raz, droga szukana raz."""
    with app.app_context():
        las1, las2, d, b = _zamowienie(LAS), _zamowienie(LAS), _zamowienie(DALEKO), _zamowienie(BLISKO)
        trasa = _trasa(b, las1, las2, d)
        ors = FakeOrs(kolejnosc=[b, las1, las2, d], daleko=[LAS], pustkowie_km=4.5)
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        jedna_pinezka = len(routing._okregi(LAS, routing.KROK_ZGRUBNY_KM, routing.MAKS_ODBICIA_KM,
                                            routing.KROK_ZGRUBNY_KM))
        assert len(ors.snapy[1]['locations']) == jedna_pinezka
        droga_vroom = [j['location'] for j in ors.optymalizacje[0]['jobs'] if j['id'] == las1][0]
        droga = (droga_vroom[1], droga_vroom[0])
        assert wynik['obecna']['km'] == pytest.approx(
            _km(BLISKO, droga, droga, DALEKO) + 2 * routing.odleglosc_km(droga, LAS), abs=0.15)


def test_przebieg_km_z_punktami_ze_snap(app):
    """(Dokładka po re-review, odpowiednik M5) Pinezka w pasie ok. 3 km: Snap ją przyciąga, Directions nie (404/2010)
    — km obu kolejności liczymy na punktach ze Snap, więc optymalizacja nie kończy się 502."""
    with app.app_context():
        d, b, sr = _zamowienie(DALEKO), _zamowienie(BLISKO), _zamowienie(SRODEK)
        trasa = _trasa(d, b, sr)
        ors = FakeOrs(kolejnosc=[b, sr, d], przesun=0.001, dir_404=[SRODEK])
        wynik = optymalizacja.zaproponuj(trasa, http_post=ors)
        assert wynik['order_ids'] == [b, sr, d]
        assert _lokalizacja(SRODEK) not in ors.przebiegi[0]
        assert [SRODEK[1] + 0.001, SRODEK[0]] in ors.przebiegi[0]


def test_odcinki_proste_w_odpowiedzi_licza_odcinki_jak_trasa(app):
    """Dokładka po re-review: `odcinki_proste` = liczba odcinków (dwa kolejne zamówienia pod jedną pinezką — jeden),
    tak samo jak `podsumowanie.odcinki_proste` trasy."""
    with app.app_context():
        las1, las2, d, b = _zamowienie(LAS), _zamowienie(LAS), _zamowienie(DALEKO), _zamowienie(BLISKO)
        trasa = _trasa(b, las1, las2, d)
        ors = FakeOrs(kolejnosc=[b, las1, las2, d], daleko=[LAS], pustkowie_km=4.5)
        assert optymalizacja.zaproponuj(trasa, http_post=ors)['odcinki_proste'] == 1
