# -*- coding: utf-8 -*-
"""Runda 2 (spec 2.5): filtr województw listy Logistyki — z kodu pocztowego, w SQL."""
from datetime import date, datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics import wojewodztwa
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import lista
from modules.reports.utils import PostcodeToStateMapper
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401


def _z(kod, kraj=None, **kolumny):
    """Zamówienie z danym kodem i krajem (fabryka zamowienie() stawia zawsze 30-001)."""
    order = zamowienie(**kolumny)
    order.delivery_postcode = kod
    order.delivery_country_code = kraj
    db.session.commit()
    return order.id


def _ids(woj, **filtry):
    return {w['id'] for w in lista.pobierz(woj=woj, **filtry)}


def test_opcje_z_mapy_raportow():
    assert [i for i, _ in wojewodztwa.wojewodztwa()] == [
        'dolnoslaskie', 'kujawsko-pomorskie', 'lubelskie', 'lubuskie', 'lodzkie', 'malopolskie',
        'mazowieckie', 'opolskie', 'podkarpackie', 'podlaskie', 'pomorskie', 'slaskie',
        'swietokrzyskie', 'warminsko-mazurskie', 'wielkopolskie', 'zachodniopomorskie']
    assert [n for _, n in wojewodztwa.wojewodztwa()] == [
        'Dolnośląskie', 'Kujawsko-Pomorskie', 'Lubelskie', 'Lubuskie', 'Łódzkie', 'Małopolskie',
        'Mazowieckie', 'Opolskie', 'Podkarpackie', 'Podlaskie', 'Pomorskie', 'Śląskie',
        'Świętokrzyskie', 'Warmińsko-Mazurskie', 'Wielkopolskie', 'Zachodniopomorskie']
    assert wojewodztwa.opcje()[16:] == (('zagranica', 'Zagranica'),
                                        ('bez_wojewodztwa', 'Bez województwa'))


def test_prefiksy_zgodne_z_mapa_raportow():
    """Jedno źródło prawdy: każdy prefiks 00–99 ma to samo województwo co Region w Routimo."""
    for n in range(100):
        kod = '%02d-100' % n
        oczekiwane = PostcodeToStateMapper.get_state_from_postcode(kod)
        znalezione = [nazwa for ident, nazwa in wojewodztwa.wojewodztwa()
                      if '%02d' % n in wojewodztwa.prefiksy(ident)]
        assert znalezione == ([oczekiwane] if oczekiwane else []), kod


@pytest.mark.parametrize('kod, woj', [
    ('34-100', 'malopolskie'), ('35-100', 'podkarpackie'),        # granica 34/35
    ('59-100', 'dolnoslaskie'), ('60-100', 'wielkopolskie'),      # granica 59/60
    ('35310', 'podkarpackie'), ('35 310', 'podkarpackie'), (' 35-310 ', 'podkarpackie'),
    ('00-950', 'mazowieckie'), ('26-600', 'mazowieckie'), ('25-001', 'swietokrzyskie'),
])
def test_granice_i_formaty_kodu(app, kod, woj):
    with app.app_context():
        oid = _z(kod)
        inne = _z('80-001')                                          # pomorskie
        assert _ids([woj]) == {oid}
        assert inne not in _ids([woj])


def test_kilka_wojewodztw_naraz(app):
    with app.app_context():
        a, b, _ = _z('35-100'), _z('31-100'), _z('80-100')
        assert _ids(['podkarpackie', 'malopolskie']) == {a, b}


def test_zagranica(app):
    with app.app_context():
        de = _z('35390', kraj='DE')                  # kod „jak z Podkarpacia”, ale kraj DE
        cz = _z('70200', kraj='cz')
        pl = _z('35-100', kraj='PL')
        pusty = _z('35-100', kraj='')
        assert _ids(['zagranica']) == {de, cz}
        assert _ids(['podkarpackie']) == {pl, pusty}


@pytest.mark.parametrize('kod', [None, '', '   ', 'brak', 'ab-123', '3', '24-100', '69-100',
                                 '88-100', '89-100', 'PL-35-310'])
def test_bez_wojewodztwa(app, kod):
    with app.app_context():
        oid = _z(kod)
        _z('35-100')
        assert _ids(['bez_wojewodztwa']) == {oid}


def test_kazde_zamowienie_w_dokladnie_jednym_kubelku(app):
    """Review Focus 1: 16 województw + Zagranica + Bez województwa dzielą zamówienia rozłącznie
    i w całości — żadne nie znika przy dowolnym wyborze, żadne nie jest w dwóch opcjach."""
    with app.app_context():
        ids = {_z(kod, kraj) for kod, kraj in [
            ('35-100', None), ('35310', 'PL'), ('35 310', 'pl'), ('00-001', ''), ('99-999', None),
            ('24-100', None), (None, None), ('', 'PL'), ('xx', None), ('35390', 'DE'),
            (None, 'UA'), ('26-600', ' PL '), ('96-100', None)]}
        opcje = [i for i, _ in wojewodztwa.opcje()]
        widziane = {}
        for opcja in opcje:
            for oid in _ids([opcja]):
                widziane.setdefault(oid, []).append(opcja)
        assert set(widziane) == ids
        assert all(len(v) == 1 for v in widziane.values()), widziane
        assert _ids(opcje) == ids


def test_woj_przed_limitem_zamknietych(app):
    """Review Focus 4 (R3): filtr w SQL przed LIMIT 50 zamkniętych — trafienie spoza
    pierwszych 50 (po id malejąco) nie może zginąć."""
    with app.app_context():
        szukane = _z('35-100', logistics_closed_at=datetime(2026, 9, 1))
        for _ in range(lista.LIMIT_ZAMKNIETYCH + 5):
            _z('80-100', logistics_closed_at=datetime(2026, 9, 1))
        wynik = lista.pobierz(q='Testowa', zamkniete=True, woj=['podkarpackie'])
        assert [w['id'] for w in wynik] == [szukane]


def test_woj_razem_z_bez_trasy_i_sposobem(app):
    """Review Focus 4: filtr województw składa się z `bez_trasy` (NOT EXISTS) i sposobem."""
    with app.app_context():
        t1 = _z('35-100', sposob=s.TRANSPORT)
        _z('80-100', sposob=s.TRANSPORT)
        _z('35-200', sposob=s.KURIER)
        na_trasie = _z('36-100', sposob=s.TRANSPORT)
        trasa = Route(name='A', date_from=date(2026, 10, 1), date_to=date(2026, 10, 1))
        db.session.add(trasa)
        db.session.flush()
        db.session.add(RouteStop(route_id=trasa.id, order_id=na_trasie, position=1))
        db.session.commit()
        assert _ids(['podkarpackie'], sposob='bez_trasy') == {t1}
        assert _ids(['podkarpackie'], sposob=s.TRANSPORT) == {t1, na_trasie}


def test_nieznane_wojewodztwo_w_serwisie_to_blad(app):
    with app.app_context():
        with pytest.raises(ValueError):
            lista.pobierz(woj=['mazowsze'])


def test_api_woj_wielokrotny_parametr(client, app):
    with app.app_context():
        a, b, _ = _z('35-100'), _z('31-100'), _z('80-100')
    dane = client.get(BASE + '/orders?woj=podkarpackie&woj=malopolskie').get_json()
    assert {o['id'] for o in dane['orders']} == {a, b}
    assert sum(dane['liczniki'].values()) == 3        # liczniki dalej liczą wszystkie otwarte


@pytest.mark.parametrize('zapytanie', ['?woj=mazowsze', '?woj=podkarpackie&woj=Podkarpackie',
                                       '?woj=zagranica&woj=%20'])
def test_api_nieznane_wojewodztwo_422(client, zapytanie):
    r = client.get(BASE + '/orders' + zapytanie)
    assert r.status_code == 422
    assert r.get_json() == {'success': False, 'error': 'Nieznany filtr województwa.'}


def test_api_pusty_woj_bez_filtra(client, app):
    with app.app_context():
        a, b = _z('35-100'), _z('80-100')
    assert {o['id'] for o in client.get(BASE + '/orders?woj=').get_json()['orders']} == {a, b}
