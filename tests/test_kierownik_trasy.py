# -*- coding: utf-8 -*-
"""GET /api/mobile/manager/routes i /routes/<id> — trasy transportu własnego na tablecie kierownika (kontrakt §8.1
i §8.2). Same odczyty: żadnego przeliczenia przebiegu (ORS), żadnego commitu poza znacznikiem kontaktu urządzenia."""
import json
from datetime import date, datetime

import pytest
import requests
from sqlalchemy import event

from extensions import db
from modules.production.kierownik.services import biala_lista, trasy
from modules.production.logistics import sposoby
from modules.production.logistics.models import LogisticsLog, OrderGeo, Route
from modules.production.logistics.services import geocoding, routing
from tests.blokady_pomocnicze import Zapytania
from tests.dostawa_pomocnicze import T0, trasa, zaladuj_wprost, zamowienie_z_paczkami
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.logistyka_fixtures import app, client, kierowca, pojazd  # noqa: F401

KIEDY = datetime(2026, 9, 25, 14, 30, 0)


@pytest.fixture()
def tablet(app):
    return tablet_kierownika()


def _get(client, tablet, sciezka, naglowki_dodatkowe=None, **parametry):
    device, kierownik = tablet
    glowki = naglowki(device, kierownik)
    glowki.update(naglowki_dodatkowe or {})
    return client.get(API + sciezka, headers=glowki, query_string=parametry)


def _ok(client, tablet, sciezka, **parametry):
    r = _get(client, tablet, sciezka, **parametry)
    assert r.status_code == 200, r.get_data()[:500]
    return r.get_json()


def _punkt(order, lat, lng, jakosc='dokladna'):
    db.session.add(OrderGeo(order_id=order.id, lat=lat, lng=lng, source='gugik', quality=jakosc,
                            address_hash='x' * 40))
    db.session.commit()


def _dwa_punkty_trasy():
    """Trasa z dwoma zamówieniami z punktami na mapie; zwraca (trasa, [zamówienia])."""
    a, _ = zamowienie_z_paczkami()
    b, _ = zamowienie_z_paczkami()
    _punkt(a, 50.06, 19.94)
    _punkt(b, 50.04, 21.99)
    return trasa([a, b]), [a, b]


def test_trasy_sa_na_liscie_endpointow():
    assert ('GET', '/routes') in ENDPOINTY_KIEROWNIKA
    assert ('GET', '/routes/<int:route_id>') in ENDPOINTY_KIEROWNIKA


# --- lista (§8.1) -----------------------------------------------------------------------------------------------

def test_lista_domyslnie_aktywne_i_30_dni(app, client, tablet):
    robocza = trasa([zamowienie_z_paczkami()[0]], status='robocza', nazwa='Robocza')
    zatwierdzona = trasa([zamowienie_z_paczkami()[0]], status='zatwierdzona', nazwa='Zatwierdzona')
    zaladowana = trasa([zamowienie_z_paczkami()[0]], status='zaladowana', nazwa='Załadowana', loaded_at=T0)
    w_trasie = trasa([zamowienie_z_paczkami()[0]], status='w_trasie', nazwa='W trasie', loaded_at=T0,
                     departed_at=T0)
    swieza = trasa([zamowienie_z_paczkami()[0]], status='wykonana', nazwa='Świeża', od=date(2026, 9, 20),
                   completed_at=T0)
    stara = trasa([zamowienie_z_paczkami()[0]], status='wykonana', nazwa='Stara', od=date(2026, 8, 1),
                  completed_at=T0)

    dane = _ok(client, tablet, '/routes')

    # Kolejność z kontraktu: w trasie, załadowane, zatwierdzone, robocze, wykonane; stara wykonana poza oknem 30 dni.
    assert [t['id'] for t in dane['trasy']] == [w_trasie.id, zaladowana.id, zatwierdzona.id, robocza.id, swieza.id]
    assert stara.id not in [t['id'] for t in dane['trasy']]


def test_lista_kolejnosc_w_grupie_wg_daty(app, client, tablet):
    pozniej = trasa([zamowienie_z_paczkami()[0]], nazwa='Później', od=date(2026, 10, 9))
    wczesniej = trasa([zamowienie_z_paczkami()[0]], nazwa='Wcześniej', od=date(2026, 10, 2))
    dane = _ok(client, tablet, '/routes')
    assert [t['id'] for t in dane['trasy']] == [wczesniej.id, pozniej.id]


def test_lista_filtry_status_od_do(app, client, tablet):
    robocza = trasa([zamowienie_z_paczkami()[0]], status='robocza', od=date(2026, 10, 5))
    zatwierdzona = trasa([zamowienie_z_paczkami()[0]], status='zatwierdzona', od=date(2026, 10, 12))
    stara = trasa([zamowienie_z_paczkami()[0]], status='wykonana', od=date(2026, 8, 1), completed_at=T0)

    assert [t['id'] for t in _ok(client, tablet, '/routes', status='robocza')['trasy']] == [robocza.id]
    # Z jawnym `od` okno 30 dni znika: stara wykonana wraca do listy (przeszukiwanie historii).
    ids = [t['id'] for t in _ok(client, tablet, '/routes', od='2026-08-01')['trasy']]
    assert stara.id in ids and robocza.id in ids and zatwierdzona.id in ids
    ids = [t['id'] for t in _ok(client, tablet, '/routes', do='2026-10-07')['trasy']]
    assert ids == [robocza.id]
    assert _ok(client, tablet, '/routes', status='wykonana', od='2026-09-01')['trasy'] == []


@pytest.mark.parametrize('parametry', [{'status': 'nieznany'}, {'od': '10.10.2026'}, {'do': 'jutro'}])
def test_lista_zly_parametr_to_400(app, client, tablet, parametry):
    r = _get(client, tablet, '/routes', **parametry)
    assert r.status_code == 400
    assert r.get_json()['error'] == 'dane_niepoprawne' and r.get_json()['message']


def test_robocza_widoczna(app, client, tablet):
    """Robocza jest na liście i w szczegółach; telefon kierowcy jej nie widzi (404), kierownik tak."""
    a, _ = zamowienie_z_paczkami()
    t = trasa([a], status='robocza', nazwa='Planowana')

    lista = _ok(client, tablet, '/routes')['trasy']
    assert [(x['id'], x['status'], x['status_etykieta']) for x in lista] == [(t.id, 'robocza', 'Robocza')]
    szczegoly = _ok(client, tablet, '/routes/%d' % t.id)['trasa']
    assert szczegoly['status'] == 'robocza' and [p['order_id'] for p in szczegoly['przystanki']] == [a.id]


def test_lista_ksztalt_naglowka_trasy(app, client, tablet):
    kierowca_ = kierowca('Piotr', 'Nowak')
    auto = pojazd(name='Iveco', capacity_kg=100, registration='RZ 12345')
    a, _ = zamowienie_z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'))
    _punkt(a, 50.06, 19.94)
    b, _ = zamowienie_z_paczkami()     # bez punktu na mapie
    t = trasa([a, b], status='zatwierdzona', nazwa='Rzeszów czw.', kierowca_id=kierowca_.id, vehicle_id=auto.id,
              notes='Zadzwonić do bramy', approved_at=KIEDY)

    w = _ok(client, tablet, '/routes')['trasy'][0]

    assert set(w) == {'id', 'nazwa', 'date_from', 'date_to', 'status', 'status_etykieta', 'pojazd', 'kierowca',
                      'notatka', 'podsumowanie', 'postep', 'zatwierdzona', 'zaladowana', 'wyjazd', 'wykonana'}
    assert (w['id'], w['nazwa'], w['date_from'], w['date_to']) == (t.id, 'Rzeszów czw.', '2026-10-01', '2026-10-01')
    assert (w['status'], w['status_etykieta']) == ('zatwierdzona', 'Zatwierdzona')
    assert w['pojazd'] == {'nazwa': 'Iveco', 'rejestracja': 'RZ 12345'}
    assert w['kierowca'] == {'id': kierowca_.id, 'nazwa': 'Piotr Nowak'}
    assert w['notatka'] == 'Zadzwonić do bramy'
    assert (w['zatwierdzona'], w['zaladowana'], w['wyjazd'], w['wykonana']) == ('2026-09-25T14:30:00', None, None, None)
    m3 = round(2 * 2 * 0.024 * 2, 4)    # 2 zamówienia × 2 pozycje × 2 sztuki × 0,024
    assert w['podsumowanie'] == {
        'przystanki': 2, 'm3': m3, 'waga_kg': int(round(m3 * sposoby.WAGA_KG_NA_M3)), 'km': None, 'minuty': None,
        'przyblizony': False, 'bez_lokalizacji': 1, 'przekroczona_ladownosc': True}
    assert w['postep'] == {'przystanki': 2, 'zaladowane': 0, 'dostarczone': 0, 'niedostarczone': 0, 'zdjete': 0}


def test_przyblizony_przebieg_ma_km_w_linii_prostej_a_minuty_null(app, client, tablet):
    """Jak w panelu (kontrakt §8.1): linie proste dają km (suma odcinków, zaniżona) i minuty null; flaga ostrzega."""
    t, _ = _dwa_punkty_trasy()
    t.geometry_approx, t.distance_km, t.duration_min = True, 412.3, None
    db.session.commit()
    p = _ok(client, tablet, '/routes')['trasy'][0]['podsumowanie']
    assert (p['przyblizony'], p['km'], p['minuty']) == (True, 412.3, None)

    t.geometry_approx, t.distance_km, t.duration_min = False, 412.3, 300
    db.session.commit()
    p = _ok(client, tablet, '/routes')['trasy'][0]['podsumowanie']
    assert (p['przyblizony'], p['km'], p['minuty']) == (False, 412.3, 300)


# --- szczegóły (§8.2) -------------------------------------------------------------------------------------------

def _trasa_ze_stanami():
    """Trasa w drodze: dostarczony, niedostarczony, „Zostaje” z częścią paczek, anulowany + jeden zdjęty z trasy."""
    dostarczony, p_dost = zamowienie_z_paczkami(statusy=('dostarczone', 'dostarczone'), delivery_company='Firma A',
                                                delivery_fullname='Jan Kowalski', client_phone='600700800',
                                                client_email='jan@example.pl')
    niedostarczony, p_nied = zamowienie_z_paczkami(statusy=('zaladowane',))
    zostaje, p_zost = zamowienie_z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), miasto='Krosno')
    anulowany, _ = zamowienie_z_paczkami(statusy=('anulowane',))
    zdjety, _ = zamowienie_z_paczkami(statusy=('czeka_na_wyciecie',), miasto='Sanok')
    t = trasa([dostarczony, niedostarczony, zostaje, anulowany], status='w_trasie', nazwa='Podkarpacie',
              loaded_at=T0, departed_at=T0)
    zaladuj_wprost(p_dost + p_nied, t)
    zaladuj_wprost(p_zost[:1], t)
    stopy = {s.order_id: s for s in t.stops}
    stopy[dostarczony.id].delivered_at = KIEDY
    stopy[niedostarczony.id].not_delivered_at = KIEDY
    stopy[niedostarczony.id].not_delivered_reason = 'brak_klienta'
    stopy[niedostarczony.id].not_delivered_note = 'nie odbiera'
    stopy[zostaje.id].stays_reason = 'brak_miejsca'
    stopy[zostaje.id].stays_note = 'wąskie drzwi'
    db.session.add(LogisticsLog(order_id=zdjety.id, route_id=t.id, action='niedostarczone', new_value='odmowa',
                                note=u'Odmowa przyjęcia: klient wyjechał', created_at=KIEDY))
    db.session.commit()
    _punkt(dostarczony, 50.0412, 21.9991)
    _punkt(niedostarczony, 49.9, 21.7, jakosc='przyblizona')
    return t, dostarczony, niedostarczony, zostaje, anulowany, zdjety


def test_szczegoly_przystanki_i_stany(app, client, tablet):
    t, dostarczony, niedostarczony, zostaje, anulowany, zdjety = _trasa_ze_stanami()

    w = _ok(client, tablet, '/routes/%d' % t.id)['trasa']

    przystanki = {p['order_id']: p for p in w['przystanki']}
    assert [p['order_id'] for p in w['przystanki']] == [dostarczony.id, niedostarczony.id, zostaje.id, anulowany.id]
    assert [p['pozycja'] for p in w['przystanki']] == [1, 2, 3, None]

    d = przystanki[dostarczony.id]
    assert set(d) == {'pozycja', 'order_id', 'numer', 'klient', 'firma', 'miasto', 'm3', 'waga_kg', 'paczki', 'stan',
                      'stan_etykieta', 'status_zbiorczy', 'zostaje', 'niedostarczone', 'dostarczono', 'geo'}
    assert d['numer'] == dostarczony.internal_order_number
    assert (d['klient'], d['firma'], d['miasto']) == ('Jan Kowalski', 'Firma A', 'Kraków')
    m3 = round(2 * 2 * 0.024, 4)
    assert (d['m3'], d['waga_kg']) == (m3, int(round(m3 * sposoby.WAGA_KG_NA_M3)))
    assert d['paczki'] == {'liczba': 2, 'zaladowane': 2}
    assert (d['stan'], d['stan_etykieta']) == ('dostarczone', 'Dostarczone')
    assert d['status_zbiorczy'] == {'status': 'dostarczone', 'etykieta': 'Dostarczone'}
    assert d['dostarczono'] == '2026-09-25T14:30:00' and d['zostaje'] is None and d['niedostarczone'] is None
    assert d['geo'] == {'lat': 50.0412, 'lng': 21.9991, 'dokladnosc': 'dokladna'}

    n = przystanki[niedostarczony.id]
    assert (n['stan'], n['stan_etykieta']) == ('niedostarczone', 'Niedostarczone')
    assert n['niedostarczone'] == {'powod': 'brak_klienta', 'etykieta': 'Brak klienta', 'notatka': 'nie odbiera',
                                   'kiedy': '2026-09-25T14:30:00'}
    assert n['dostarczono'] is None
    assert n['geo'] == {'lat': 49.9, 'lng': 21.7, 'dokladnosc': 'przyblizona'}

    z = przystanki[zostaje.id]
    assert (z['stan'], z['stan_etykieta']) == ('zweryfikowane', 'Zweryfikowane')
    assert z['zostaje'] == {'powod': 'brak_miejsca', 'etykieta': 'Brak miejsca', 'notatka': 'wąskie drzwi'}
    assert z['paczki'] == {'liczba': 2, 'zaladowane': 1} and z['miasto'] == 'Krosno'
    assert z['geo'] is None      # adres nie znaleziony: brak wiersza punktu

    a = przystanki[anulowany.id]
    assert (a['stan'], a['stan_etykieta'], a['pozycja']) == ('anulowane', 'Anulowane', None)
    assert a['status_zbiorczy'] == {'status': 'anulowane', 'etykieta': 'Anulowane'}

    assert w['niedostarczone_zdjete'] == [{
        'order_id': zdjety.id, 'numer': zdjety.internal_order_number, 'klient': zdjety.client_name,
        'miasto': 'Sanok', 'powod_etykieta': 'Odmowa przyjęcia', 'notatka': 'klient wyjechał',
        'kiedy': '2026-09-25T14:30:00'}]
    # Postęp jak w panelu: niedostarczone = na trasie + zdjęte do puli.
    assert w['postep'] == {'przystanki': 3, 'zaladowane': 2, 'dostarczone': 1, 'niedostarczone': 2, 'zdjete': 1}
    assert w['magazyn'] == {'lat': geocoding.MAGAZYN['lat'], 'lng': geocoding.MAGAZYN['lng'],
                            'nazwa': geocoding.MAGAZYN['nazwa']}


def test_przystanek_z_problemem_ma_etykiete_z_powodem(app, client, tablet):
    a, _ = zamowienie_z_paczkami()
    a.problem_at, a.problem_reason = KIEDY, 'brak_materialu'
    db.session.commit()
    t = trasa([a])
    stan = _ok(client, tablet, '/routes/%d' % t.id)['trasa']['przystanki'][0]
    assert stan['stan'] == 'problem' and stan['stan_etykieta'].startswith('PROBLEM: ')


def test_status_zbiorczy_przystanku_jak_w_karcie_zamowienia(app, client, tablet):
    """Pozycje na różnych etapach: `status` null i „Różne (x/n)” — liczone także z anulowanymi, jak karta (§5.2)."""
    rozne, _ = zamowienie_z_paczkami(statusy=('zweryfikowane', 'czeka_na_wyciecie', 'anulowane'))
    jeden, _ = zamowienie_z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'))
    t = trasa([rozne, jeden])

    przystanki = {p['order_id']: p for p in _ok(client, tablet, '/routes/%d' % t.id)['trasa']['przystanki']}
    assert przystanki[rozne.id]['status_zbiorczy'] == {'status': None, 'etykieta': u'Różne (1/3)'}
    assert przystanki[jeden.id]['status_zbiorczy'] == {'status': 'zweryfikowane', 'etykieta': 'Zweryfikowane'}
    karta = _ok(client, tablet, '/orders/%d' % rozne.id)['zamowienie']
    assert przystanki[rozne.id]['status_zbiorczy'] == karta['status_zbiorczy']


def test_status_zbiorczy_bez_zapytania_na_przystanek(app, client, tablet):
    """Pozycje wszystkich zamówień trasy jednym zapytaniem: liczba zapytań nie rośnie z liczbą przystanków."""
    def _liczba_zapytan(przystankow):
        t = trasa([zamowienie_z_paczkami()[0] for _ in range(przystankow)])
        db.session.expire_all()
        with Zapytania() as zapytania:
            _ok(client, tablet, '/routes/%d' % t.id)
        return len(zapytania.lista)

    assert _liczba_zapytan(1) == _liczba_zapytan(4)


# --- przebieg: tylko zapisany, bez przeliczania (Review Focus 4) -------------------------------------------------

ORS_ODP = {'type': 'FeatureCollection', 'features': [{
    'geometry': {'type': 'LineString', 'coordinates': [[22.25, 49.84], [19.94, 50.06], [21.99, 50.04], [22.25, 49.84]]},
    'properties': {'summary': {'distance': 412345.6, 'duration': 18000.0}}}]}


class _Odp(object):
    status_code = 200

    def json(self):
        return ORS_ODP

    def raise_for_status(self):
        pass


def _przelicz_jak_web(app, t, klucz=True):
    """Stan, który zostawia po sobie panel tras: przeliczony przebieg zapisany w trasie (z kluczem ORS po drogach)."""
    if klucz:
        app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    else:
        app.config.pop('OPENROUTESERVICE_API_KEY', None)
    punkty = geocoding.geo_zamowien([s.order_id for s in t.stops])
    assert routing.przelicz(t, punkty, http_post=lambda *a, **k: _Odp()) is True
    db.session.commit()


def test_przebieg_brak_nieaktualny_bez_geo(app, client, tablet):
    # Trasa nigdy nie przeliczona: brak geometrii, serwer niczego nie liczy.
    t, (a, b) = _dwa_punkty_trasy()
    w = _ok(client, tablet, '/routes/%d' % t.id)['trasa']
    assert w['przebieg'] is None and w['przebieg_nieaktualny'] is True and w['odcinki_proste'] == []
    assert Route.query.get(t.id).geometry_json is None and Route.query.get(t.id).geometry_hash is None

    # Przebieg po drogach policzony przez panel: aktualny, oddany bez przeliczania.
    _przelicz_jak_web(app, t)
    w = _ok(client, tablet, '/routes/%d' % t.id)['trasa']
    assert w['przebieg'] == ORS_ODP['features'][0]['geometry']
    assert w['przebieg_nieaktualny'] is False

    # Przystanek przesunięty na mapie od ostatniego przeliczenia: podajemy ostatni zapisany przebieg i flagę.
    OrderGeo.query.filter_by(order_id=b.id).update({'lat': 50.5})
    db.session.commit()
    w = _ok(client, tablet, '/routes/%d' % t.id)['trasa']
    assert w['przebieg'] == ORS_ODP['features'][0]['geometry'] and w['przebieg_nieaktualny'] is True


def test_przebieg_linie_proste_bez_klucza_sa_aktualne_do_zmiany_przystanku(app, client, tablet):
    """Linie proste (brak klucza ORS, błąd ORS) mają w trasie skrót z dopiskiem, nie zwykły — mimo to nie są
    „nieaktualne”, dopóki punkty się nie zmienią."""
    t, (a, b) = _dwa_punkty_trasy()
    _przelicz_jak_web(app, t, klucz=False)
    assert Route.query.get(t.id).geometry_approx is True
    w = _ok(client, tablet, '/routes/%d' % t.id)['trasa']
    assert w['przebieg']['type'] == 'LineString' and w['przebieg_nieaktualny'] is False
    assert w['podsumowanie']['przyblizony'] is True

    OrderGeo.query.filter_by(order_id=a.id).update({'lng': 20.5})
    db.session.commit()
    assert _ok(client, tablet, '/routes/%d' % t.id)['trasa']['przebieg_nieaktualny'] is True


def test_przebieg_po_zmianie_kolejnosci_przystankow_jest_nieaktualny(app, client, tablet):
    t, (a, b) = _dwa_punkty_trasy()
    _przelicz_jak_web(app, t)
    stopy = {s.order_id: s for s in t.stops}
    stopy[a.id].position, stopy[b.id].position = 2, 1
    db.session.commit()
    assert _ok(client, tablet, '/routes/%d' % t.id)['trasa']['przebieg_nieaktualny'] is True


def test_przystanek_bez_ordergeo_ma_geo_null(app, client, tablet):
    a, _ = zamowienie_z_paczkami()
    t = trasa([a])
    w = _ok(client, tablet, '/routes/%d' % t.id)['trasa']
    assert w['przystanki'][0]['geo'] is None and w['podsumowanie']['bez_lokalizacji'] == 1


def test_przebieg_nie_zawiera_odcinkow_prostych_w_geometrii_a_pole_je_podaje(app, client, tablet):
    t, _ = _dwa_punkty_trasy()
    odcinek = [[21.9, 50.0], [21.99, 50.04]]
    t.geometry_json = json.dumps({'type': 'LineString', 'coordinates': [[22.25, 49.84], [21.99, 50.04]],
                                  'odcinki_proste': [odcinek]})
    db.session.commit()
    w = _ok(client, tablet, '/routes/%d' % t.id)['trasa']
    assert 'odcinki_proste' not in w['przebieg']
    assert w['odcinki_proste'] == [odcinek]


def test_przebieg_aktualny_czysta_funkcja(app):
    t, _ = _dwa_punkty_trasy()
    assert trasy.przebieg_aktualny(t) == (None, True)
    _przelicz_jak_web(app, t)
    przebieg, nieaktualny = trasy.przebieg_aktualny(t)
    assert przebieg['type'] == 'LineString' and nieaktualny is False


def test_odczyt_bez_ors_i_bez_commitu(app, client, tablet, monkeypatch):
    """Panel tras przelicza przebieg w samym GET (ORS po HTTP i commit). Kierownik czyta tylko to, co zapisane."""
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'      # z kluczem panel poszedłby po ORS
    t = _trasa_ze_stanami()[0]
    t2, _ = _dwa_punkty_trasy()                         # trasa z nieaktualnym (nigdy niepoliczonym) przebiegiem

    def _zakaz(*a, **k):
        raise AssertionError('Odczyt kierownika wywołał przeliczenie przebiegu albo ruch sieciowy')
    monkeypatch.setattr(routing, 'przelicz', _zakaz)
    monkeypatch.setattr(routing, 'zapytaj_przebieg', _zakaz)
    monkeypatch.setattr(routing, 'snap_ors', _zakaz)
    monkeypatch.setattr(requests, 'post', _zakaz)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', _zakaz)

    for sciezka in ('/routes', '/routes/%d' % t.id, '/routes/%d' % t2.id):
        with Zapytania() as zapytania:
            def _commit(conn):
                zapytania.lista.append(('COMMIT', None))
            event.listen(db.engine, 'commit', _commit)
            try:
                _ok(client, tablet, sciezka)
            finally:
                event.remove(db.engine, 'commit', _commit)
        sql = [s for s, _p in zapytania.lista]
        # Jedyny commit to znacznik kontaktu urządzenia (require_device_token); po nim tylko SELECT-y.
        assert sql.count('COMMIT') == 1, (sciezka, sql.count('COMMIT'))
        po_commicie = sql[sql.index('COMMIT') + 1:]
        assert po_commicie, sciezka
        assert not [s for s in po_commicie if s.startswith(('INSERT', 'UPDATE', 'DELETE'))], (sciezka, po_commicie)
        assert not [s for s in sql if s.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))], sciezka

    # Nic się nie zapisało w trasie: geometria i skrót zostały takie, jak były (puste).
    assert Route.query.get(t2.id).geometry_json is None and Route.query.get(t2.id).geometry_hash is None


# --- prywatność -------------------------------------------------------------------------------------------------

def test_trasy_bez_zakazanych(app, client, tablet):
    t, dostarczony, *_ = _trasa_ze_stanami()
    # W bazie siedzą dane, których kierownik nie ma widzieć: ulica, telefon, e-mail (patrz _trasa_ze_stanami).
    assert dostarczony.client_phone == '600700800' and dostarczony.delivery_address and dostarczony.client_email
    for sciezka in ('/routes', '/routes/%d' % t.id):
        r = _get(client, tablet, sciezka)
        assert r.status_code == 200
        assert biala_lista.zakazane_w(r.get_json()) == [], sciezka
        tekst = r.get_data(as_text=True)
        for tajne in ('600700800', 'jan@example.pl', dostarczony.delivery_address, '30-001'):
            assert tajne not in tekst, (sciezka, tajne)


# --- błędy i pamięć podręczna -----------------------------------------------------------------------------------

def test_trasa_nieznana_404(app, client, tablet):
    r = _get(client, tablet, '/routes/999999')
    assert r.status_code == 404
    assert r.get_json()['error'] == 'trasa_nieznana' and r.get_json()['message']


def test_bramka_wymaga_profilu_kierownika(app, client, tablet):
    device, _ = tablet
    for sciezka in ('/routes', '/routes/1'):
        r = client.get(API + sciezka, headers=naglowki(device))
        assert r.status_code == 400 and r.get_json()['error'] == 'worker_required'


def test_etag_304_listy(app, client, tablet):
    t = trasa([zamowienie_z_paczkami()[0]], status='robocza')
    r = _get(client, tablet, '/routes')
    etag = r.headers['ETag']
    assert etag.startswith('W/"') and r.headers['Cache-Control'] == 'private, max-age=15'

    r = _get(client, tablet, '/routes', naglowki_dodatkowe={'If-None-Match': etag})
    assert r.status_code == 304 and r.headers['ETag'] == etag and r.get_data() == b''

    t.name = 'Inna nazwa'
    db.session.commit()
    r = _get(client, tablet, '/routes', naglowki_dodatkowe={'If-None-Match': etag})
    assert r.status_code == 200 and r.headers['ETag'] != etag

    # Inny filtr to inna odpowiedź, więc inny ETag.
    assert _get(client, tablet, '/routes', status='wykonana').headers['ETag'] != r.headers['ETag']


def test_etag_szczegolow_max_age_0(app, client, tablet):
    t = trasa([zamowienie_z_paczkami()[0]], status='robocza')
    r = _get(client, tablet, '/routes/%d' % t.id)
    etag = r.headers['ETag']
    assert etag.startswith('W/"') and r.headers['Cache-Control'] == 'private, max-age=0'

    r = _get(client, tablet, '/routes/%d' % t.id, naglowki_dodatkowe={'If-None-Match': etag})
    assert r.status_code == 304 and r.headers['Cache-Control'] == 'private, max-age=0'

    t.notes = 'Nowa notatka'
    db.session.commit()
    r = _get(client, tablet, '/routes/%d' % t.id, naglowki_dodatkowe={'If-None-Match': etag})
    assert r.status_code == 200 and r.get_json()['trasa']['notatka'] == 'Nowa notatka'


def test_kierowca_i_postep_budowane_pole_po_polu():
    """Nowe pola panelu w `kierowca` albo `postep` (np. telefon kierowcy) nie trafiają na tablet bez decyzji."""
    assert trasy._kierowca(None) is None
    assert trasy._kierowca({'id': 21, 'nazwa': 'Piotr Nowak', 'telefon': '500100200', 'phone': '1'}) == \
        {'id': 21, 'nazwa': 'Piotr Nowak'}
    postep = dict.fromkeys(trasy.KLUCZE_POSTEPU, 1)
    assert set(trasy._postep(dict(postep, kontakt='x'))) == {
        'przystanki', 'zaladowane', 'dostarczone', 'niedostarczone', 'zdjete'}
