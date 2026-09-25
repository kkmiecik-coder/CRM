# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime

import pytest
import requests
from sqlalchemy import event, text

from extensions import db
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import delivery, dzierzawa
from modules.production.logistics.services import geocoding as g
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401
from tests.test_logistyka_geocoding import (
    BACHORZ, FLORIANSKA, NAZWA_LOGGERA, FakeHttp, FakeHttpAwariaZUrl, Odp,
)


def _bez_spania(_):
    pass


def _bachorz():
    """Zamówienie z adresem magazynu — GUGiK (BACHORZ) daje dokładny punkt przy kodzie 36-065."""
    order = zamowienie(miasto='Bachórz')
    order.delivery_address, order.delivery_postcode = 'Bachórz 14N', '36-065'
    db.session.commit()
    return order


def _nagrywaj_postep(monkeypatch):
    """UF3: każdy zapis postępu geokodera (JSON jako dict, '' jako '')."""
    zapisy = []
    prawdziwy = dzierzawa.zapisz

    def zapisz(klucz, wartosc):
        if klucz == g.KLUCZ_POSTEPU:
            zapisy.append(json.loads(wartosc) if wartosc else wartosc)
        return prawdziwy(klucz, wartosc)

    monkeypatch.setattr(dzierzawa, 'zapisz', zapisz)
    return zapisy


def _pary(zapisy):
    return [(z['wszystkie'], z['zrobione']) for z in zapisy if z != '']


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
        # Kod 36-065 (R9): domyślny kod fiksturki (30-001, Kraków) ma inny prefiks niż
        # trafienie GUGiK dla Bachorza, więc nie dałby już dokładnego punktu.
        order = _bachorz()
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


@pytest.mark.parametrize('lat, lng', [(None, 19.9), (91, 19.9), (50, 181), ('x', 1),
                                      (True, 19.9), (50, False), (True, False)])
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
        db.session.commit()
        order_ok = _bachorz()

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
    """Wyjątek POZA obsługą jednego zamówienia (tu: baza przy odnawianiu dzierżawy)
    przerywa przebieg, ale dzierżawa wraca do puli, a postęp jest wyczyszczony.
    (I1: wyjątek z `zlokalizuj_zamowienie` już przebiegu nie przerywa — patrz
    test_wyjatek_jednego_zamowienia_nie_blokuje_nastepnego.)"""
    with app.app_context():
        zamowienie(miasto='Kraków').delivery_address = 'Floriańska 10'
        db.session.commit()
        zapisy = _nagrywaj_postep(monkeypatch)

        def _wybuchnij(*a, **k):
            raise RuntimeError('boom')

        monkeypatch.setattr(dzierzawa, 'odnow', _wybuchnij)
        with pytest.raises(RuntimeError):
            g.lokalizuj(http_get=FakeHttp(), spij=_bez_spania)
        # Dzierżawa musi wrócić do puli mimo wyjątku - kolejny przebieg ją przejmuje.
        assert zapisy[0]['wszystkie'] == 1 and zapisy[-1] == ''
        assert dzierzawa.przejmij(g.KLUCZ_DZIERZAWY, g.CZAS_DZIERZAWY_S) is not None
        assert g.postep() is None


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
        order_ok.delivery_address, order_ok.delivery_postcode = 'Bachórz 14N', '36-065'
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


# ── I1: jeden zły rekord nie przerywa przebiegu i nie głodzi nowszych zamówień ──

def test_zly_rekord_gugik_nie_glodzi_nowszych_zamowien(app):
    """Trafienie GUGiK z pustym `y` rzucało ValueError poza try — przebieg padał, a następny
    (ta sama kolejność) znów na nim."""
    with app.app_context():
        zly = zamowienie(miasto='Kraków')
        zly.delivery_address, zly.delivery_postcode = 'Floriańska 10', '31-021'
        db.session.commit()
        ok = _bachorz()
        zle = {'type': 'address', 'results': {'1': dict(FLORIANSKA['results']['1'], y='')}}
        http = FakeHttp(gugik={'Kraków, Floriańska 10': zle, 'Bachórz 14N': BACHORZ})
        wynik = g.lokalizuj(http_get=http, spij=_bez_spania)
        assert wynik['zamowienia'] == 2 and wynik['bledy'] == 0
        geo_ok = OrderGeo.query.get(ok.id)
        assert (geo_ok.source, geo_ok.quality) == ('gugik', 'dokladna')
        assert OrderGeo.query.get(zly.id).quality == 'nie_znaleziono'


def test_wyjatek_jednego_zamowienia_nie_blokuje_nastepnego(app, monkeypatch, caplog):
    with app.app_context():
        zly = zamowienie(miasto='Kraków')
        zly.delivery_address = 'Floriańska 10'
        db.session.commit()
        zly_id = zly.id
        ok = _bachorz()
        prawdziwa = g.zlokalizuj_zamowienie

        def zlokalizuj(order, http_get=None, spij=None):
            if order.id == zly_id:
                raise RuntimeError('boom')
            return prawdziwa(order, http_get=http_get, spij=spij)

        monkeypatch.setattr(g, 'zlokalizuj_zamowienie', zlokalizuj)
        with caplog.at_level(logging.ERROR, logger=NAZWA_LOGGERA):
            wynik = g.lokalizuj(http_get=FakeHttp(gugik={'Bachórz 14N': BACHORZ}), spij=_bez_spania)
        assert (wynik['bledy'], wynik['zamowienia'], wynik['dokladne']) == (1, 1, 1)
        assert OrderGeo.query.get(ok.id).source == 'gugik'
        assert OrderGeo.query.get(zly_id) is None
        tekst = '\n'.join(r.getMessage() for r in caplog.records if r.name == NAZWA_LOGGERA)
        assert '"order_id": %d' % zly_id in tekst and 'RuntimeError' in tekst
        assert 'Traceback' in tekst
        assert dzierzawa.przejmij(g.KLUCZ_DZIERZAWY, g.CZAS_DZIERZAWY_S) is not None


def test_wyjatki_zamowien_nie_licza_sie_do_serii_pelnych_awarii(app, monkeypatch):
    with app.app_context():
        for _ in range(g.MAKS_BLEDOW_Z_RZEDU + 1):
            zamowienie()

        def _wybuchnij(order, http_get=None, spij=None):
            raise RuntimeError('boom')

        monkeypatch.setattr(g, 'zlokalizuj_zamowienie', _wybuchnij)
        wynik = g.lokalizuj(http_get=FakeHttp(), spij=_bez_spania)
        assert wynik['bledy'] == g.MAKS_BLEDOW_Z_RZEDU + 1


def test_reset_rownolegly_zaraz_po_zapisie_nie_psuje_przebiegu(app, monkeypatch):
    """`punkt.source` czytane PO commicie: równoległy reset (DELETE z innego procesu)
    między commitem a odczytem dawał ObjectDeletedError."""
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        order.delivery_address, order.delivery_postcode = 'Floriańska 10', '31-021'
        db.session.commit()
        oid = order.id
        prawdziwy_commit = db.session.commit

        def commit_i_reset():
            prawdziwy_commit()
            # Logistyk klika „Resetuj” w tej samej chwili: DELETE tuż po naszym zapisie.
            if db.session.execute(text('SELECT COUNT(*) FROM prod_order_geo WHERE order_id = :id'),
                                  {'id': oid}).scalar():
                db.session.execute(text('DELETE FROM prod_order_geo WHERE order_id = :id'),
                                   {'id': oid})
                prawdziwy_commit()

        monkeypatch.setattr(db.session, 'commit', commit_i_reset)
        wynik = g.lokalizuj(http_get=FakeHttp(gugik={'Kraków, Floriańska 10': FLORIANSKA}),
                            spij=_bez_spania)
        assert (wynik['zamowienia'], wynik['dokladne'], wynik['bledy']) == (1, 1, 0)


# ── M3: log awarii z order_id, bez adresu klienta ──

def test_log_awarii_w_przebiegu_ma_order_id_bez_adresu(app, caplog):
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        order.delivery_address, order.delivery_postcode = 'Floriańska 10', '31-021'
        db.session.commit()
        oid = order.id
        with caplog.at_level(logging.DEBUG, logger=NAZWA_LOGGERA):
            wynik = g.lokalizuj(http_get=FakeHttpAwariaZUrl(), spij=_bez_spania)
        assert wynik['bledy'] == 1
    tekst = '\n'.join(r.getMessage() for r in caplog.records if r.name == NAZWA_LOGGERA)
    assert '"order_id": %d' % oid in tekst
    assert 'Floria' not in tekst and 'Krak' not in tekst and '31-021' not in tekst


# ── R11: kolejka przebiegu ──

def test_kolejka_najpierw_nowe_i_zmienione_potem_ponowienia(app):
    with app.app_context():
        ponowienie = zamowienie()   # najniższe id, ale czeka na koniec kolejki
        zmienione = zamowienie()
        nowe = zamowienie()
        db.session.add(OrderGeo(order_id=ponowienie.id, quality='nie_znaleziono', attempts=1,
                                address_hash=g.skrot_adresu(ponowienie)))
        db.session.add(OrderGeo(order_id=zmienione.id, lat=50.0, lng=20.0, source='gugik',
                                quality='dokladna', address_hash='x' * 40))
        db.session.commit()
        assert g.do_zlokalizowania() == [zmienione, nowe, ponowienie]


def test_zamowienie_dodane_w_trakcie_przebiegu_nie_czeka_godziny(app, monkeypatch):
    """Po przerobieniu listy jedno ponowne do_zlokalizowania() (bez już przerobionych);
    zamówienie dodane w trakcie TEGO dołożenia czeka już na kolejny przebieg."""
    with app.app_context():
        _bachorz()
        zapisy = _nagrywaj_postep(monkeypatch)
        prawdziwy = FakeHttp(gugik={'Bachórz 14N': BACHORZ})
        stan = {'n': 0}

        def http_get(url, params=None, timeout=None, headers=None):
            stan['n'] += 1
            if stan['n'] == 1:
                stan['drugie'] = _bachorz().id    # w trakcie pierwszej listy
            elif stan['n'] == 2:
                stan['trzecie'] = _bachorz().id   # w trakcie dołożonych
            return prawdziwy(url, params=params, timeout=timeout, headers=headers)

        wynik = g.lokalizuj(http_get=http_get, spij=_bez_spania)
        assert wynik['zamowienia'] == 2
        assert OrderGeo.query.get(stan['drugie']).quality == 'dokladna'
        assert OrderGeo.query.get(stan['trzecie']) is None
        assert _pary(zapisy) == [(1, 0), (1, 1), (2, 1), (2, 2)]
        assert zapisy[-1] == ''


def test_dolozenie_pomija_zamowienia_z_bledem_w_tym_przebiegu(app):
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        order.delivery_address = 'Floriańska 10'
        db.session.commit()
        http = FakeHttp(awaria={'gugik', 'nominatim'})
        wynik = g.lokalizuj(http_get=http, spij=_bez_spania)
        assert wynik['bledy'] == 1
        # jedno zamówienie = jedno zapytanie GUGiK, drugi raz nie wraca w tym samym przebiegu
        assert len([u for u, _, _ in http.wywolania if u == g.GUGIK_URL]) == 1


# ── UF3: postęp geokodera dla „Zlokalizuj teraz” ──

def test_postep_rosnie_po_kazdym_zamowieniu(app, monkeypatch):
    """Postęp po KAŻDYM zamówieniu: wyjątek, pominięty ręczny, awaria usług, sukces;
    na końcu wyczyszczony."""
    with app.app_context():
        wyjatek = zamowienie(miasto='Kraków')
        wyjatek.delivery_address = 'Wadliwa 1'
        reczny = zamowienie(miasto='Kraków')
        reczny.delivery_address = 'Reczna 2'
        awaria = zamowienie(miasto='Kraków')
        awaria.delivery_address = 'Awaryjna 3'
        db.session.commit()
        _bachorz()
        wyjatek_id = wyjatek.id
        zapisy = _nagrywaj_postep(monkeypatch)

        prawdziwa = g.zlokalizuj_zamowienie

        def zlokalizuj(order, http_get=None, spij=None):
            if order.id == wyjatek_id:
                raise RuntimeError('boom')
            return prawdziwa(order, http_get=http_get, spij=spij)

        monkeypatch.setattr(g, 'zlokalizuj_zamowienie', zlokalizuj)
        prawdziwy = FakeHttp(gugik={'Bachórz 14N': BACHORZ})
        stan = {'reczny': False}

        def http_get(url, params=None, timeout=None, headers=None):
            tekst = (params or {}).get('address') or (params or {}).get('street') or ''
            if 'Awaryjna' in tekst:
                raise requests.ConnectionError('awaria testowa')
            if 'Reczna' in tekst and not stan['reczny']:
                stan['reczny'] = True
                g.ustaw_recznie(reczny, 50.05, 19.95)
                db.session.commit()
            return prawdziwy(url, params=params, timeout=timeout, headers=headers)

        wynik = g.lokalizuj(http_get=http_get, spij=_bez_spania)
        assert (wynik['bledy'], wynik['zamowienia']) == (2, 1)
        assert _pary(zapisy) == [(4, 0), (4, 1), (4, 2), (4, 3), (4, 4)]
        assert zapisy[-1] == ''
        assert all(isinstance(z['od'], str) for z in zapisy if z != '')
        assert g.postep() is None


def test_postep_tylko_przy_zywej_dzierzawie(app):
    with app.app_context():
        dzierzawa.zapisz(g.KLUCZ_POSTEPU, json.dumps(
            {'wszystkie': 5, 'zrobione': 2, 'od': '2026-09-25T10:00:00'}))
        # osierocony wpis po padniętym procesie — dzierżawa wygasła
        assert g.postep() is None
        assert dzierzawa.przejmij(g.KLUCZ_DZIERZAWY, g.CZAS_DZIERZAWY_S) is not None
        assert g.postep() == {'zrobione': 2, 'wszystkie': 5}


@pytest.mark.parametrize('wartosc', ['', 'x', '[]', '{"zrobione": 1}',
                                     '{"zrobione": "1", "wszystkie": 2}',
                                     '{"zrobione": true, "wszystkie": 2}',
                                     '1970-01-01T00:00:00'])
def test_postep_nieczytelny_to_none(app, wartosc):
    with app.app_context():
        assert dzierzawa.przejmij(g.KLUCZ_DZIERZAWY, g.CZAS_DZIERZAWY_S) is not None
        dzierzawa.zapisz(g.KLUCZ_POSTEPU, wartosc)
        assert g.postep() is None


def test_zapis_postepu_nie_rusza_updated_at(app):
    """Jak dzierżawa: MAX(prod_config.updated_at) wchodzi do ETagu tabletów."""
    with app.app_context():
        wiersz = dzierzawa.wiersz(g.KLUCZ_POSTEPU)
        przed = wiersz.updated_at
        dzierzawa.zapisz(g.KLUCZ_POSTEPU, '{"wszystkie": 1, "zrobione": 0}')
        db.session.expire_all()
        wiersz = dzierzawa.wiersz(g.KLUCZ_POSTEPU)
        assert wiersz.config_value == '{"wszystkie": 1, "zrobione": 0}'
        assert wiersz.updated_at == przed


# ── M5: licznik „bez lokalizacji” jednym zapytaniem ──

def test_bez_lokalizacji_jednym_zapytaniem(app):
    with app.app_context():
        zamowienie()                                               # brak punktu — liczy się
        nz, dok, prz = zamowienie(), zamowienie(), zamowienie()
        zamowienie(logistics_closed_at=datetime(2026, 9, 1))       # zamknięte — nie
        db.session.add(OrderGeo(order_id=nz.id, quality='nie_znaleziono', address_hash='x' * 40))
        for order, jakosc in ((dok, 'dokladna'), (prz, 'przyblizona')):
            db.session.add(OrderGeo(order_id=order.id, lat=50, lng=20, source='gugik',
                                    quality=jakosc, address_hash='x' * 40))
        db.session.commit()
        zapytania = []

        def nasluch(conn, cursor, statement, parameters, context, executemany):
            zapytania.append(statement)

        event.listen(db.engine, 'before_cursor_execute', nasluch)
        try:
            wynik = g.bez_lokalizacji()
        finally:
            event.remove(db.engine, 'before_cursor_execute', nasluch)
        assert wynik == 2
        assert len(zapytania) == 1, zapytania
