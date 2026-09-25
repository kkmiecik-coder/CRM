# -*- coding: utf-8 -*-
from datetime import datetime

import pytest
import requests

from extensions import db
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import delivery, dzierzawa
from modules.production.logistics.services import geocoding as g
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401
from tests.test_logistyka_geocoding import BACHORZ, FLORIANSKA, FakeHttp, Odp


def _bez_spania(_):
    pass


def test_lokalizuje_otwarte_i_zapisuje(app):
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        order.delivery_address, order.delivery_postcode = 'Floriańska 10', '31-021'
        db.session.commit()
        http = FakeHttp(gugik={'Kraków, Floriańska 10': FLORIANSKA})
        wynik = g.lokalizuj(http_get=http, spij=_bez_spania)
        assert wynik['dokladne'] == 1 and wynik['dzierzawa'] is True
        geo = OrderGeo.query.get(order.id)
        assert (geo.source, geo.quality) == ('gugik', 'dokladna')
        assert geo.address_hash == g.skrot_adresu(order)


def test_zamkniete_nie_sa_lokalizowane(app):
    with app.app_context():
        zamowienie(logistics_closed_at=datetime(2026, 9, 1))
        assert g.do_zlokalizowania() == []


def test_nie_znaleziono_zuzywa_proby_do_limitu(app):
    with app.app_context():
        order = zamowienie(miasto='Xyz')
        order.delivery_address = 'Nowa 5'
        db.session.commit()
        for _ in range(g.MAKS_PROB):
            g.zlokalizuj_zamowienie(order, FakeHttp(nominatim=[[], []]), _bez_spania)
            db.session.commit()
        assert OrderGeo.query.get(order.id).attempts == g.MAKS_PROB
        assert g.do_zlokalizowania() == []


def test_awaria_uslug_nie_zuzywa_prob(app):
    """Review Focus 2."""
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        order.delivery_address = 'Floriańska 10'
        db.session.commit()
        wynik = g.lokalizuj(http_get=FakeHttp(awaria={'gugik', 'nominatim'}), spij=_bez_spania)
        assert wynik['bledy'] == 1
        assert OrderGeo.query.get(order.id) is None
        assert g.do_zlokalizowania() == [order]


def test_zmiana_adresu_lokalizuje_od_nowa(app):
    with app.app_context():
        order = zamowienie(miasto='Bachórz')
        order.delivery_address = 'Bachórz 14N'
        db.session.commit()
        g.zlokalizuj_zamowienie(order, FakeHttp(gugik={'Bachórz 14N': BACHORZ}), _bez_spania)
        db.session.commit()
        assert g.do_zlokalizowania() == []
        order.delivery_address = 'Bachórz 15'
        db.session.commit()
        assert g.do_zlokalizowania() == [order]


def test_reczny_punkt_przezywa_zmiane_adresu(app):
    """Review Focus 3."""
    with app.app_context():
        order = zamowienie()
        g.ustaw_recznie(order, 50.05, 19.95)
        db.session.commit()
        order.delivery_address = 'Inna 1'
        db.session.commit()
        assert g.do_zlokalizowania() == []
        assert g.oznacz_zmienione_reczne() == 1
        geo = OrderGeo.query.get(order.id)
        assert (float(geo.lat), geo.source) == (50.05, 'reczna')
        assert geo.address_changed_after_manual is True


@pytest.mark.parametrize('lat, lng', [(None, 19.9), (91, 19.9), (50, 181), ('x', 1)])
def test_reczny_punkt_walidacja(app, lat, lng):
    with app.app_context():
        with pytest.raises(delivery.LogistykaBlad) as e:
            g.ustaw_recznie(zamowienie(), lat, lng)
        assert e.value.status == 422


def test_reset_oddaje_zamowienie_automatowi(app):
    with app.app_context():
        order = zamowienie()
        g.ustaw_recznie(order, 50.05, 19.95)
        db.session.commit()
        g.resetuj(order)
        db.session.commit()
        assert OrderGeo.query.get(order.id) is None


def test_zamowienie_bez_adresu_bez_zapytan(app):
    """Review Focus 5."""
    with app.app_context():
        order = zamowienie(delivery_method='Odbiór osobisty')
        order.delivery_address = order.delivery_city = order.delivery_postcode = None
        db.session.commit()
        http = FakeHttp()
        geo = g.zlokalizuj_zamowienie(order, http, _bez_spania)
        db.session.commit()
        assert http.wywolania == []
        assert geo.quality == 'nie_znaleziono' and geo.attempts == g.MAKS_PROB
        assert g.bez_lokalizacji() == 1


def test_drugi_geokoder_nie_startuje(app):
    """Review Focus 4."""
    with app.app_context():
        zamowienie()
        assert dzierzawa.przejmij(g.KLUCZ_DZIERZAWY, g.CZAS_DZIERZAWY_S) is not None
        wynik = g.lokalizuj(http_get=FakeHttp(), spij=_bez_spania)
        assert wynik['dzierzawa'] is False and wynik['zamowienia'] == 0
        assert g.geokoder_dziala() is True


# ── R2 (kontroler): seria awarii przerywa przebieg, dzierzawa zawsze zwolniona ────

def test_seria_bledow_przerywa_przebieg(app):
    """4 zamówienia, usługi cały czas padają -> przebieg staje po MAKS_BLEDOW_Z_RZEDU."""
    with app.app_context():
        orders = [zamowienie(miasto='Kraków') for _ in range(4)]
        for order in orders:
            order.delivery_address = 'Floriańska 10'
        db.session.commit()
        http = FakeHttp(awaria={'gugik', 'nominatim'})
        wynik = g.lokalizuj(http_get=http, spij=_bez_spania)
        assert wynik['bledy'] == g.MAKS_BLEDOW_Z_RZEDU
        assert wynik['zamowienia'] == 0
        # 4. zamówienie nigdy nie trafiło do usług - zostaje bez punktu, ale też bez próby
        assert OrderGeo.query.get(orders[3].id) is None
        assert orders[3] in g.do_zlokalizowania()


def test_pojedynczy_blad_nie_przerywa_przebiegu(app):
    """Pierwsze zamówienie pada, drugie ma sprawne usługi -> drugie jest zapisane."""
    with app.app_context():
        order_zly = zamowienie(miasto='Kraków')
        order_zly.delivery_address = 'Floriańska 10'
        order_ok = zamowienie(miasto='Bachórz')
        order_ok.delivery_address = 'Bachórz 14N'
        db.session.commit()

        class FakeHttpMieszany(object):
            """GUGiK/Nominatim padają dla zapytań Floriańskiej, Bachórz przechodzi normalnie."""

            def __init__(self):
                self.wywolania = []

            def __call__(self, url, params=None, timeout=None, headers=None):
                self.wywolania.append((url, dict(params or {}), dict(headers or {})))
                if url == g.GUGIK_URL and params.get('address') == 'Bachórz 14N':
                    return Odp(BACHORZ)
                raise requests.ConnectionError('awaria testowa')

        http = FakeHttpMieszany()
        wynik = g.lokalizuj(http_get=http, spij=_bez_spania)
        assert wynik['bledy'] == 1
        assert wynik['zamowienia'] == 1
        geo_ok = OrderGeo.query.get(order_ok.id)
        assert geo_ok is not None and (geo_ok.source, geo_ok.quality) == ('gugik', 'dokladna')
        assert OrderGeo.query.get(order_zly.id) is None


def test_dzierzawa_zwolniona_po_wyjatku(app, monkeypatch):
    with app.app_context():
        zamowienie(miasto='Kraków').delivery_address = 'Floriańska 10'
        db.session.commit()

        def _wybuchnij(order, http_get=None, spij=None):
            raise RuntimeError('boom')

        monkeypatch.setattr(g, 'zlokalizuj_zamowienie', _wybuchnij)
        with pytest.raises(RuntimeError):
            g.lokalizuj(http_get=FakeHttp(), spij=_bez_spania)
        # Dzierżawa musi wrócić do puli mimo wyjątku - kolejny przebieg ją przejmuje.
        assert dzierzawa.przejmij(g.KLUCZ_DZIERZAWY, g.CZAS_DZIERZAWY_S) is not None


# ── R6 (kontroler): punkt ustawiony ręcznie nigdy nie jest nadpisany ─────────────

def test_reczny_punkt_na_wejsciu_bez_zapytan(app):
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        order.delivery_address = 'Floriańska 10'
        g.ustaw_recznie(order, 50.05, 19.95)
        db.session.commit()
        http = FakeHttp(gugik={'Kraków, Floriańska 10': FLORIANSKA})
        geo = g.zlokalizuj_zamowienie(order, http, _bez_spania)
        assert http.wywolania == []
        assert (geo.source, float(geo.lat), float(geo.lng)) == ('reczna', 50.05, 19.95)


def test_reczny_punkt_ustawiony_w_trakcie_nie_jest_nadpisany(app):
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        order.delivery_address = 'Floriańska 10'
        db.session.commit()

        prawdziwy = FakeHttp(gugik={'Kraków, Floriańska 10': FLORIANSKA})
        stan = {'pierwsze': True}

        def http_get(url, params=None, timeout=None, headers=None):
            if stan['pierwsze']:
                stan['pierwsze'] = False
                g.ustaw_recznie(order, 50.05, 19.95)
                db.session.commit()
            return prawdziwy(url, params=params, timeout=timeout, headers=headers)

        geo = g.zlokalizuj_zamowienie(order, http_get, _bez_spania)
        db.session.commit()
        assert (geo.source, float(geo.lat), float(geo.lng)) == ('reczna', 50.05, 19.95)
        odczyt = OrderGeo.query.get(order.id)
        assert (odczyt.source, float(odczyt.lat), float(odczyt.lng)) == ('reczna', 50.05, 19.95)


def test_lokalizuj_nie_liczy_pominietego_punktu_recznego(app):
    """R6(c), poprawka rundy 1: `zlokalizuj_zamowienie` może oddać ISTNIEJĄCY punkt
    reczny bez zapisu (tu: ustawiony przez logistyka W TRAKCIE geokodowania tego
    zamówienia) - `lokalizuj` nie ma prawa policzyć tego jako geokodowanie ani ruszyć
    serią błędów, mimo że commit się udaje (nic nie było brudne do zapisania)."""
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        order.delivery_address = 'Floriańska 10'
        db.session.commit()

        prawdziwy = FakeHttp(gugik={'Kraków, Floriańska 10': FLORIANSKA})
        stan = {'pierwsze': True}

        def http_get(url, params=None, timeout=None, headers=None):
            if stan['pierwsze']:
                stan['pierwsze'] = False
                g.ustaw_recznie(order, 50.05, 19.95)
                db.session.commit()
            return prawdziwy(url, params=params, timeout=timeout, headers=headers)

        wynik = g.lokalizuj(http_get=http_get, spij=_bez_spania)
        assert wynik['zamowienia'] == 0
        assert wynik['dokladne'] == 0
        assert wynik['bledy'] == 0
        geo = OrderGeo.query.get(order.id)
        assert (geo.source, float(geo.lat), float(geo.lng)) == ('reczna', 50.05, 19.95)


# ── R7 (kontroler): tylko PEŁNA awaria liczy się do serii przerywającej przebieg ──

def test_awaria_czesciowa_nie_przerywa_serii(app):
    """Awaria częściowa (GUGiK trwale pada, Nominatim zawsze odpowiada - tu tylko
    przybliżeniem, które R3 każe odrzucić) liczy się do wynik['bledy'], ale NIE
    wydłuża serii przerywającej `lokalizuj` - inaczej garstka trwale wadliwych
    starych zamówień (niższe id -> przetwarzane pierwsze) zagłodziłaby wszystkie
    nowsze, mimo że usługi jako całość działają."""
    with app.app_context():
        for _ in range(4):
            zamowienie(miasto='Kraków')
        db.session.commit()

        class FakeHttpCzesciowaAwaria(object):
            """GUGiK zawsze pada, Nominatim zawsze odpowiada, ale tylko przybliżeniem."""

            def __init__(self):
                self.wywolania = []

            def __call__(self, url, params=None, timeout=None, headers=None):
                self.wywolania.append((url, dict(params or {}), dict(headers or {})))
                if url == g.GUGIK_URL:
                    raise requests.ConnectionError('awaria testowa GUGiK')
                return Odp([{'lat': '50.1', 'lon': '19.9', 'place_rank': 26}])

        http = FakeHttpCzesciowaAwaria()
        wynik = g.lokalizuj(http_get=http, spij=_bez_spania)
        # Wszystkie 4 zamowienia przetworzone - zadne nie zablokowalo reszty przebiegu.
        assert wynik['bledy'] == 4
        assert wynik['zamowienia'] == 0


def test_sukces_resetuje_serie_bledow_z_rzedu(app):
    """Pełna awaria, pełna awaria, SUKCES, pełna awaria, pełna awaria - sukces w
    środku zeruje licznik, więc przebieg NIE przerywa się mimo 4 błędów łącznie
    (bez zerowania: 2 błędy + 1 kolejny po sukcesie = 3 z rzędu -> przerwanie
    przed piątym zamówieniem)."""
    with app.app_context():
        adresy_krakow = ['Floriańska 10', 'Floriańska 11', 'Floriańska 13', 'Floriańska 14']
        orders = []
        for adr in adresy_krakow[:2]:
            order = zamowienie(miasto='Kraków')
            order.delivery_address = adr
            orders.append(order)
        order_ok = zamowienie(miasto='Bachórz')
        order_ok.delivery_address = 'Bachórz 14N'
        orders.append(order_ok)
        for adr in adresy_krakow[2:]:
            order = zamowienie(miasto='Kraków')
            order.delivery_address = adr
            orders.append(order)
        db.session.commit()

        class FakeHttpSeria(object):
            """Pelna awaria dla kazdego adresu poza Bachórz 14N (GUGiK i Nominatim padaja)."""

            def __init__(self):
                self.wywolania = []

            def __call__(self, url, params=None, timeout=None, headers=None):
                self.wywolania.append((url, dict(params or {}), dict(headers or {})))
                if url == g.GUGIK_URL and params.get('address') == 'Bachórz 14N':
                    return Odp(BACHORZ)
                raise requests.ConnectionError('awaria testowa')

        http = FakeHttpSeria()
        wynik = g.lokalizuj(http_get=http, spij=_bez_spania)
        assert wynik['bledy'] == 4
        assert wynik['zamowienia'] == 1
        # Wszystkie 5 zamowien przetworzone (bez przerwania) - kazdy z 5 roznych
        # adresow zostal odpytany w GUGiK-u.
        zapytane_adresy = {p['address'] for u, p, h in http.wywolania if u == g.GUGIK_URL}
        assert len(zapytane_adresy) == 5
