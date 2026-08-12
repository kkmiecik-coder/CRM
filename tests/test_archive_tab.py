# -*- coding: utf-8 -*-
"""
Zakładka Archiwum — filtry, paginacja i liczba zapytań SQL.

Archiwum trzyma całą historię firmy (2300+ spakowanych pozycji na produkcji),
więc chronimy tu trzy rzeczy naraz:
  1. że jedno wejście na zakładkę to garść zapytań, a nie jedno na produkt,
  2. że serwer oddaje JEDNĄ stronę, a nie cały zbiór do HTML-a,
  3. że filtry liczone w bazie dają ten sam wynik, co dawniej filtr w JS
     (OR w obrębie filtra, AND między filtrami, dopasowanie na poziomie
     ZAMÓWIENIA — wystarczy jedna pasująca pozycja).
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionOrder, ProductionProduct,
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker,
    ProductionWorkerSession, ProductionDevice,
)
from modules.users.models import User
# Te importy nie są tu używane wprost, ale configure_mappers() przy pierwszym
# zapytaniu konfiguruje CAŁY rejestr mapperów — bez nich wywala się na
# relationship('Multiplier') / ('Client') / ('QuoteStatus').
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

BASE = '/production/api'

# LONGTEXT (MySQL) nie istnieje w SQLite — jak w tests/test_worker_stats.py
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker,
)]


@pytest.fixture()
def app():
    """
    Minimalna apka z blueprintem API produkcji.

    LOGIN_DISABLED neutralizuje login_required — testujemy zapytania i filtry,
    nie Flask-Login (ten nie ma tu skonfigurowanego LoginManagera).
    """
    app = Flask(__name__, template_folder=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'modules', 'production', 'templates'))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['LOGIN_DISABLED'] = True

    from modules.production.routers.api import api_bp
    app.register_blueprint(api_bp, url_prefix=BASE)
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


class LicznikZapytan:
    """Zlicza zapytania SQL wykonane w bloku `with`."""

    def __init__(self, engine):
        self.engine = engine
        self.zapytania = []

    def __enter__(self):
        event.listen(self.engine, 'before_cursor_execute', self._zapisz)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, 'before_cursor_execute', self._zapisz)
        return False

    def _zapisz(self, conn, cursor, statement, parameters, context, executemany):
        self.zapytania.append(statement)

    def __len__(self):
        return len(self.zapytania)


def _config(species='dąb', technology='lity', wood_class='A/B'):
    cfg = ProductionConfiguration.query.filter_by(
        species=species, technology=technology, wood_class=wood_class).first()
    if not cfg:
        cfg = ProductionConfiguration(species=species, technology=technology,
                                      wood_class=wood_class)
        db.session.add(cfg)
        db.session.flush()
    return cfg


def _zamowienie(app, numer, pozycje, client_name='Jan Kowalski',
                bl_id=None, client_order_number=None, quote_number=None):
    """
    Tworzy zamówienie z listą pozycji. Każda pozycja to dict z opcjonalnymi
    kluczami: status, species, technology, wood_class, thickness, name,
    packaging_completed_at, created_at, volume, value, quantity.
    """
    with app.app_context():
        order = ProductionOrder(
            baselinker_order_id=bl_id or (10000 + int(str(abs(hash(numer)))[:5])),
            internal_order_number=numer,
            client_name=client_name,
            client_order_number=client_order_number,
            quote_number=quote_number,
        )
        db.session.add(order)
        db.session.flush()
        for idx, poz in enumerate(pozycje, start=1):
            cfg = _config(poz.get('species', 'dąb'),
                          poz.get('technology', 'lity'),
                          poz.get('wood_class', 'A/B'))
            produkt = ProductionProduct(
                order_id=order.id,
                configuration_id=cfg.id,
                short_product_id=f'{numer.replace("/", "")}_{idx}',
                product_sequence_in_order=idx,
                original_product_name=poz.get('name', 'Blat dębowy'),
                current_status=poz.get('status', 'spakowane'),
                parsed_thickness_cm=poz.get('thickness', 4.0),
                volume_m3=poz.get('volume', 0.1),
                total_value_net=poz.get('value', 1000),
                quantity=poz.get('quantity', 1),
                packaging_completed_at=poz.get('packaging_completed_at'),
                created_at=poz.get('created_at'),
            )
            db.session.add(produkt)
        db.session.commit()
        return order.id


def _archiwum(client, **params):
    qs = '&'.join(
        f'{k}={v}' for k, values in params.items()
        for v in (values if isinstance(values, (list, tuple)) else [values])
    )
    r = client.get(f'{BASE}/products-tab-content?view=archive' + (f'&{qs}' if qs else ''))
    assert r.status_code == 200, r.get_data()[:500]
    dane = r.get_json()
    assert dane['success'] is True
    return dane['initial_data']


def _numery(dane):
    """Numery zamówień w kolejności, w jakiej przyszły produkty."""
    out = []
    for p in dane['products']:
        if p['internal_order_number'] not in out:
            out.append(p['internal_order_number'])
    return out


def _pelne_archiwum(app):
    """Zestaw danych używany przez większość testów."""
    baza = datetime(2026, 5, 10, 12, 0, 0)
    _zamowienie(app, '26/00001', [
        {'species': 'dąb', 'technology': 'lity', 'wood_class': 'A/B', 'thickness': 4.0,
         'packaging_completed_at': baza, 'created_at': baza - timedelta(days=10)},
    ], client_name='Anna Nowak', bl_id=555001)
    _zamowienie(app, '26/00002', [
        {'species': 'buk', 'technology': 'mikrowczep', 'wood_class': 'B/B', 'thickness': 2.5,
         'packaging_completed_at': baza + timedelta(days=1),
         'created_at': baza - timedelta(days=5)},
        {'species': 'jesion', 'technology': 'lity', 'wood_class': 'A/B', 'thickness': 4.0,
         'name': 'Parapet jesionowy',
         'packaging_completed_at': baza + timedelta(days=1),
         'created_at': baza - timedelta(days=5)},
    ], client_name='Piotr Zieliński', bl_id=555002)
    # Niearchiwalne — jedna pozycja wciąż w produkcji
    _zamowienie(app, '26/00003', [
        {'status': 'spakowane', 'packaging_completed_at': baza},
        {'status': 'czeka_na_wyciecie'},
    ], client_name='Firma Trzecia', bl_id=555003)
    # W całości anulowane — też archiwum. Celowo osobny gatunek i grubość,
    # żeby nie wpadało przypadkiem do wyników testów filtrów.
    _zamowienie(app, '26/00004', [
        {'status': 'anulowane', 'species': 'modrzew', 'thickness': 6.0},
    ], client_name='Klient Anulowany', bl_id=555004)
    return baza


# --- N+1 -------------------------------------------------------------------

def test_liczba_zapytan_nie_rosnie_z_liczba_zamowien(app, client):
    """
    Sedno całej zmiany: koszt jednego wejścia w archiwum ma być stały.

    Wcześniej serializer robił COUNT per produkt i doczytywał prod_orders /
    prod_configurations relacją — na produkcji dawało to 3152 zapytania.
    """
    baza = datetime(2026, 5, 10, 12, 0, 0)
    for i in range(1, 13):
        _zamowienie(app, f'26/{i:05d}', [
            {'packaging_completed_at': baza + timedelta(days=i),
             'created_at': baza},
            {'packaging_completed_at': baza + timedelta(days=i),
             'created_at': baza},
        ], bl_id=600000 + i)

    with app.app_context():
        with LicznikZapytan(db.engine) as licznik_malo:
            _archiwum(client)
        liczba_malo = len(licznik_malo)

    for i in range(13, 41):
        _zamowienie(app, f'26/{i:05d}', [
            {'packaging_completed_at': baza + timedelta(days=i),
             'created_at': baza},
            {'packaging_completed_at': baza + timedelta(days=i),
             'created_at': baza},
        ], bl_id=600000 + i)

    with app.app_context():
        with LicznikZapytan(db.engine) as licznik_duzo:
            _archiwum(client)
        liczba_duzo = len(licznik_duzo)

    assert liczba_malo == liczba_duzo, (
        f'liczba zapytań rośnie z rozmiarem archiwum: {liczba_malo} → {liczba_duzo}')
    assert liczba_duzo <= 10, f'za dużo zapytań na jedno wejście: {liczba_duzo}'


def test_serializer_nie_dolicza_pozycji_zamowienia_per_produkt(app, client):
    """
    `total_products_in_order` musi lecieć z jednego GROUP BY, nie z COUNT-a
    na każdą pozycję — to był największy pojedynczy udział w N+1.
    """
    _zamowienie(app, '26/00001', [{}, {}, {}],
                bl_id=555001)
    dane = _archiwum(client)
    assert [p['total_products_in_order'] for p in dane['products']] == [3, 3, 3]


# --- PAGINACJA -------------------------------------------------------------

def test_serwer_oddaje_jedna_strone_a_nie_calosc(app, client):
    """Bez tego 919 zamówień ląduje w jednym HTML-u (6,5 MB na produkcji)."""
    baza = datetime(2026, 5, 10, 12, 0, 0)
    for i in range(1, 31):
        _zamowienie(app, f'26/{i:05d}',
                    [{'packaging_completed_at': baza + timedelta(days=i)}],
                    bl_id=600000 + i)

    dane = _archiwum(client)
    assert dane['pagination']['total_orders'] == 30
    assert dane['pagination']['total_pages'] == 2
    assert dane['pagination']['has_next'] is True
    assert dane['pagination']['has_prev'] is False
    assert len(_numery(dane)) == dane['pagination']['per_page']


def test_strony_nie_gubia_i_nie_dubluja_zamowien(app, client):
    """
    Sortowanie po dacie zakończenia musi mieć deterministyczny remis — przy
    równych datach zamówienie potrafiłoby inaczej wypaść na stronie 1 i 2.
    """
    baza = datetime(2026, 5, 10, 12, 0, 0)
    for i in range(1, 31):
        # ta sama data zakończenia dla wszystkich → same remisy
        _zamowienie(app, f'26/{i:05d}', [{'packaging_completed_at': baza}],
                    bl_id=600000 + i)

    zebrane = []
    strona1 = _archiwum(client, page=1)
    zebrane += _numery(strona1)
    zebrane += _numery(_archiwum(client, page=2))

    assert len(zebrane) == 30
    assert len(set(zebrane)) == 30


def test_sortowanie_od_najnowszego_zakonczenia(app, client):
    baza = datetime(2026, 5, 10, 12, 0, 0)
    _zamowienie(app, '26/00001', [{'packaging_completed_at': baza}], bl_id=555001)
    _zamowienie(app, '26/00002',
                [{'packaging_completed_at': baza + timedelta(days=3)}], bl_id=555002)
    _zamowienie(app, '26/00003',
                [{'packaging_completed_at': baza + timedelta(days=1)}], bl_id=555003)

    assert _numery(_archiwum(client)) == ['26/00002', '26/00003', '26/00001']


def test_numer_strony_poza_zakresem_jest_docinany(app, client):
    _zamowienie(app, '26/00001', [{'packaging_completed_at': datetime(2026, 5, 10)}],
                bl_id=555001)
    dane = _archiwum(client, page=9999)
    assert dane['pagination']['page'] == 1
    assert len(dane['products']) == 1


# --- CO WCHODZI DO ARCHIWUM ------------------------------------------------

def test_do_archiwum_wchodza_tylko_zamowienia_domkniete(app, client):
    """
    Archiwalne = wszystkie pozycje spakowane ALBO wszystkie anulowane.
    Zamówienie z jedną pozycją w produkcji musi zostać na liście aktywnych.
    """
    _pelne_archiwum(app)
    numery = _numery(_archiwum(client))
    assert '26/00003' not in numery, 'zamówienie w produkcji wpadło do archiwum'
    assert set(numery) == {'26/00001', '26/00002', '26/00004'}


# --- FILTRY: SEMANTYKA -----------------------------------------------------

def test_filtr_dopasowuje_zamowienie_po_jednej_pozycji(app, client):
    """
    Filtr wybiera CAŁE zamówienia — wystarczy jedna pasująca pozycja, a karta
    pokazuje wtedy wszystkie pozycje zamówienia (tak działał filtr w JS).
    """
    _pelne_archiwum(app)
    dane = _archiwum(client, wood_species='jesion')
    assert _numery(dane) == ['26/00002']
    # obie pozycje zamówienia, nie tylko jesionowa
    assert len(dane['products']) == 2


def test_wielokrotny_wybor_dziala_jak_or(app, client):
    _pelne_archiwum(app)
    dane = _archiwum(client, wood_species=['dąb', 'buk'])
    assert set(_numery(dane)) == {'26/00001', '26/00002'}


def test_rozne_filtry_dzialaja_jak_and(app, client):
    _pelne_archiwum(app)
    # 26/00002 ma pozycję bukową (mikrowczep) i jesionową (lity) — oba warunki
    # spełnione, choć przez DWIE różne pozycje. Tak samo liczył to JS.
    dane = _archiwum(client, wood_species='buk', technology='lity')
    assert _numery(dane) == ['26/00002']

    # dąb + mikrowczep nie występuje w żadnym zamówieniu
    assert _archiwum(client, wood_species='dąb',
                     technology='mikrowczep')['pagination']['total_orders'] == 0


def test_filtr_grubosci_trafia_w_wartosci_calkowite(app, client):
    """
    Regresja: backend zwracał opcję '4.0cm', a JS porównywał '4cm' (bo JSON-owe
    4.0 to w JS liczba 4) — filtr grubości dla całkowitych wartości nie działał.
    """
    _pelne_archiwum(app)
    assert '4cm' in _archiwum(client)['filters']['thicknesses']
    assert set(_numery(_archiwum(client, thickness='4cm'))) == {'26/00001', '26/00002'}
    assert _numery(_archiwum(client, thickness='2.5cm')) == ['26/00002']


def test_wyszukiwarka_szuka_po_polach_zamowienia_i_pozycji(app, client):
    _pelne_archiwum(app)
    assert _numery(_archiwum(client, search='Zieliński')) == ['26/00002']
    assert _numery(_archiwum(client, search='26/00001')) == ['26/00001']
    assert _numery(_archiwum(client, search='Parapet')) == ['26/00002']
    assert _archiwum(client, search='nic-takiego')['pagination']['total_orders'] == 0


def test_wyszukiwarka_znajduje_zamowienie_po_id_baselinkera(app, client):
    """W JS haystackiem był `bl-<id>`, więc muszą działać oba zapisy."""
    _pelne_archiwum(app)
    assert _numery(_archiwum(client, search='bl-555002')) == ['26/00002']
    assert _numery(_archiwum(client, search='555002')) == ['26/00002']


def test_zakres_dat_filtruje_po_dacie_zakonczenia_zamowienia(app, client):
    baza = _pelne_archiwum(app)
    dzien = baza.strftime('%Y-%m-%d')
    # "do" jest włącznie — zamówienie zakończone tego dnia ma się załapać
    dane = _archiwum(client, completed_from=dzien, completed_to=dzien)
    assert _numery(dane) == ['26/00001']


def test_filtry_lacza_sie_z_paginacja(app, client):
    """
    Licznik wyników i liczba stron muszą dotyczyć wyniku PO filtrach —
    inaczej pager prowadzi na puste strony.
    """
    baza = datetime(2026, 5, 10, 12, 0, 0)
    for i in range(1, 31):
        _zamowienie(app, f'26/{i:05d}', [{
            'species': 'dąb' if i <= 10 else 'buk',
            'packaging_completed_at': baza + timedelta(days=i),
        }], bl_id=600000 + i)

    dane = _archiwum(client, wood_species='dąb')
    assert dane['pagination']['total_orders'] == 10
    assert dane['pagination']['total_pages'] == 1
    assert dane['pagination']['has_next'] is False
    assert len(_numery(dane)) == 10


# --- STATYSTYKI ------------------------------------------------------------

def test_statystyki_dotycza_calego_wyniku_a_nie_widocznej_strony(app, client):
    """
    Kafelki nad listą mają pokazywać sumy z całego przefiltrowanego archiwum.
    Liczone z widocznej strony pokazywałyby „ostatnie 25 zamówień".
    """
    baza = datetime(2026, 5, 10, 12, 0, 0)
    for i in range(1, 31):
        _zamowienie(app, f'26/{i:05d}', [{
            'packaging_completed_at': baza + timedelta(days=i),
            'created_at': baza,
            'volume': 0.5, 'value': 100, 'quantity': 2,
        }], bl_id=600000 + i)

    dane = _archiwum(client)
    arch = dane['stats']['archive']
    assert arch['orders_count'] == 30
    assert arch['products_count'] == 30
    assert arch['total_value'] == pytest.approx(3000.0)
    assert arch['total_volume'] == pytest.approx(30.0)  # 30 × 0.5 m³ × 2 szt
    assert len(dane['products']) == 25  # strona nadal ograniczona


def test_statystyki_reaguja_na_filtry(app, client):
    _pelne_archiwum(app)
    pelne = _archiwum(client)['stats']['archive']
    zawezone = _archiwum(client, wood_species='buk')['stats']['archive']
    assert zawezone['orders_count'] == 1
    assert zawezone['orders_count'] < pelne['orders_count']


def test_sredni_czas_realizacji_liczony_per_zamowienie(app, client):
    baza = datetime(2026, 5, 10, 12, 0, 0)
    _zamowienie(app, '26/00001', [{
        'packaging_completed_at': baza,
        'created_at': baza - timedelta(days=10),
    }], bl_id=555001)
    _zamowienie(app, '26/00002', [{
        'packaging_completed_at': baza,
        'created_at': baza - timedelta(days=20),
    }], bl_id=555002)

    assert _archiwum(client)['stats']['archive']['avg_realization_days'] == pytest.approx(15.0)


# --- LISTY WARTOŚCI DO FILTRÓW --------------------------------------------

def test_opcje_filtrow_obejmuja_cale_archiwum_nie_tylko_strone(app, client):
    """
    Przy paginacji nie da się zebrać opcji z załadowanych zamówień — gatunek
    z 40. zamówienia musi być na liście, choć na pierwszej stronie go nie ma.
    """
    baza = datetime(2026, 5, 10, 12, 0, 0)
    for i in range(1, 31):
        # 'jesion' ma tylko NAJSTARSZE zamówienie, więc na 1. stronie go nie ma
        _zamowienie(app, f'26/{i:05d}', [{
            'species': 'jesion' if i == 1 else 'dąb',
            'packaging_completed_at': baza + timedelta(days=i),
        }], bl_id=600000 + i)

    dane = _archiwum(client)
    assert 'jesion' not in {p['parsed_wood_species'] for p in dane['products']}
    assert 'jesion' in dane['filters']['wood_species']


def test_opcje_filtrow_zawezaja_sie_do_zakresu_dat(app, client):
    baza = _pelne_archiwum(app)
    dzien = baza.strftime('%Y-%m-%d')
    dane = _archiwum(client, completed_from=dzien, completed_to=dzien)
    # W tym dniu zakończono tylko dębowe 26/00001
    assert dane['filters']['wood_species'] == ['dąb']


def test_opcje_grubosci_sa_posortowane_liczbowo(app, client):
    _zamowienie(app, '26/00001', [
        {'thickness': 10.0}, {'thickness': 2.0}, {'thickness': 1.5},
    ], bl_id=555001)
    assert _archiwum(client)['filters']['thicknesses'] == ['1.5cm', '2cm', '10cm']


# --- PUSTY STAN ------------------------------------------------------------

def test_pusty_wynik_ma_spojna_paginacje_i_statystyki(app, client):
    _pelne_archiwum(app)
    dane = _archiwum(client, search='nie-ma-takiego-klienta')
    assert dane['products'] == []
    assert dane['pagination']['total_orders'] == 0
    assert dane['pagination']['total_pages'] == 1
    assert dane['pagination']['has_next'] is False
    assert dane['stats']['archive']['orders_count'] == 0
    assert dane['stats']['archive']['avg_realization_days'] is None
