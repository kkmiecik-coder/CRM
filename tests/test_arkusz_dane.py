# -*- coding: utf-8 -*-
"""Dane siatki arkusza: grupowanie po zamowieniu, kolumny wyliczane,
kolumny z produkcji, szukajka, filtr, stronicowanie i podsumowanie.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime
from decimal import Decimal

import pytest
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionOrder, ProductionProduct,
)
from modules.reports import reports_bp
from modules.reports.arkusz_service import dane_arkusza, kolumny_z_adresu
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.users.models import User

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

# LONGTEXT (MySQL) nie istnieje w SQLite — jak w tests/krawedzie_fixtures.py:56
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

_TABLES = [m.__table__ for m in (
    User, SalesClient, SalesOrder, SalesOrderItem,
    ProductionConfig, ProductionOrder, ProductionProduct, ProductionConfiguration,
)]

OKNO = {'od': '2026-09-01', 'do': '2026-09-30'}


def zamowienie(bl_id, dzien=18, **nadpisania):
    pola = dict(baselinker_order_id=bl_id, date_created=date(2026, 9, dzien),
                customer_name='Jan Przykładowy', internal_order_number='WP-0912',
                email='jan.przykladowy@example.com', delivery_state='śląskie',
                caretaker='Łukasz Próbny', client_origin='Stały B2B',
                paid_amount=Decimal('1000.00'), paid_cash=Decimal('0.00'),
                balance_due=Decimal('0.00'), current_status='W produkcji - surowe')
    pola.update(nadpisania)
    zam = SalesOrder(**pola)
    db.session.add(zam)
    db.session.flush()
    return zam


def pozycja(zam, netto='800.00', objetosc='0.010000', grupa='towar',
            bl_pozycja=991, gatunek='dąb'):
    poz = SalesOrderItem(
        order_id=zam.id, bl_order_product_id=bl_pozycja, wood_species=gatunek,
        technology='lity', wood_class='A/B', group_type=grupa, quantity=1,
        length_cm=Decimal('100.00'), width_cm=Decimal('50.00'),
        thickness_cm=Decimal('2.00'), price_gross=Decimal('984.00'),
        price_net=Decimal(netto), value_net=Decimal(netto),
        total_volume=Decimal(objetosc), raw_product_name='Blat dębowy lity A/B')
    db.session.add(poz)
    db.session.flush()
    return poz


def produkcja(bl_id, znaczniki):
    """znaczniki: lista datetime|None, po jednym na pozycje produkcyjna."""
    zam = ProductionOrder(baselinker_order_id=bl_id, internal_order_number='26_00001')
    db.session.add(zam)
    db.session.flush()
    for i, znacznik in enumerate(znaczniki, start=1):
        db.session.add(ProductionProduct(
            order_id=zam.id, short_product_id=f'26_{i:05d}',
            product_sequence_in_order=i, original_product_name='Blat',
            quantity=1, gluing_completed_at=znacznik))
    db.session.flush()
    return zam


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    app.config['SECRET_KEY'] = 'test'
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def klient_http(app):
    from modules.users.services.permission_service import PermissionService
    oryginal = PermissionService.user_has_module_access
    PermissionService.user_has_module_access = staticmethod(lambda u, m: True)

    app.register_blueprint(reports_bp)
    app.add_url_rule('/login', 'login', lambda: 'login')
    pulpit = Blueprint('dashboard', __name__)
    pulpit.add_url_rule('/dashboard', 'dashboard', lambda: 'pulpit')
    app.register_blueprint(pulpit)
    app.jinja_loader = ChoiceLoader([
        DictLoader({'sidebar/sidebar.html': '<nav></nav>',
                    'access_denied.html': '<p>{{ module_name }}</p>'}),
        app.jinja_loader,
    ])
    with app.app_context():
        db.session.add(User(email='ma@woodpower.pl', password='x', role='user', active=True))
        db.session.commit()
    klient = app.test_client()
    with klient.session_transaction() as sesja:
        sesja['user_email'] = 'ma@woodpower.pl'
    yield klient
    PermissionService.user_has_module_access = oryginal


def _dane(**nadpisania):
    argumenty = {'od': date(2026, 9, 1), 'do': date(2026, 9, 30)}
    argumenty.update(nadpisania)
    return dane_arkusza(**argumenty)


# ===== grupowanie i scalanie ===========================================

def test_wiersze_sa_pogrupowane_po_zamowieniu_z_liczba_wierszy(app):
    with app.app_context():
        zam = zamowienie(50854536)
        for i in range(3):
            pozycja(zam, bl_pozycja=991 + i)
        db.session.commit()

        wynik = _dane()
        assert len(wynik['zamowienia']) == 1
        assert wynik['zamowienia'][0]['wierszy'] == 3
        assert len(wynik['zamowienia'][0]['pozycje']) == 3


def test_pola_poziomu_zamowienia_sa_raz_na_zamowienie(app):
    # To jest strukturalna gwarancja reguly „edycja scalonej komorki
    # to JEDEN UPDATE na sales_orders": pole poziomu zamowienia nie ma
    # jak trafic na pozycje, bo go tam po prostu nie ma.
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam)
        pozycja(zam, bl_pozycja=992)
        db.session.commit()

        zamowienia = _dane()['zamowienia']
        assert 'customer_name' in zamowienia[0]['pola']
        for poz in zamowienia[0]['pozycje']:
            assert 'customer_name' not in poz['pola']
            assert 'paid_amount' not in poz['pola']


def test_zamowienie_bez_pozycji_daje_jeden_pusty_wiersz(app):
    # Zamowienie bez pozycji jest dzis niemozliwe, ale po Planie C osiagalne
    # (BaseLinker potrafi zwrocic zamowienie, w ktorym wszystkie pozycje
    # zostaly usuniete). rowspan=0 rozwalilby tabele, wiec minimum to 1.
    with app.app_context():
        zamowienie(50854536)
        db.session.commit()
        zam = _dane()['zamowienia'][0]
        assert zam['wierszy'] == 1
        assert zam['pozycje'] == []


# ===== kolumny wyliczane na poziomie zamowienia ========================

def test_kwota_netto_zamowienia_liczy_sie_na_serwerze(app):
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam, netto='800.00')
        pozycja(zam, netto='200.00', bl_pozycja=992)
        db.session.commit()
        assert _dane(kolumny=['order_amount_net'])['zamowienia'][0]['pola'][
            'order_amount_net'] == '1 000,00'


def test_objetosc_zamowienia_wyklucza_uslugi(app):
    # 17 wierszy na produkcji ma total_volume > 1, glownie suszenie uslugowe
    # („Suszenie usługowe 88m3"). Wrzesien 2025 pokazywal przez to 167 m3
    # zamiast okolo 12.
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam, objetosc='0.010000')
        pozycja(zam, objetosc='88.000000', grupa='usługa', bl_pozycja=992)
        db.session.commit()
        assert _dane(kolumny=['total_m3'])['zamowienia'][0]['pola'][
            'total_m3'] == '0,010000'


def test_czas_realizacji_liczy_sie_z_daty_zejscia_z_produkcji(app):
    with app.app_context():
        zam = zamowienie(50854536, dzien=1)
        pozycja(zam)
        prod = produkcja(50854536, [datetime(2026, 9, 5, 7, 42)])
        prod.logistics_completed_at = datetime(2026, 9, 11, 16, 0)
        db.session.commit()
        pola = _dane(kolumny=['lead_time_days', 'logistics_done_at'])['zamowienia'][0]['pola']
        assert pola['lead_time_days'] == '10'
        assert pola['logistics_done_at'] == '11.09.2026 16:00'


def test_czas_realizacji_pusty_bez_daty_zejscia(app):
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam)
        db.session.commit()
        assert _dane(kolumny=['lead_time_days'])['zamowienia'][0]['pola'][
            'lead_time_days'] == '—'


# ===== kolumny z produkcji =============================================

def test_kolumna_produkcji_pusta_dopoki_nie_wszystkie_pozycje_gotowe(app):
    # „Sklejone" ma znaczyc „cale zamowienie sklejone", nie „cos sklejono".
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam)
        produkcja(50854536, [datetime(2026, 9, 18, 7, 42), None])
        db.session.commit()
        assert _dane(kolumny=['gluing_done_at'])['zamowienia'][0]['pola'][
            'gluing_done_at'] == '—'


def test_kolumna_produkcji_pokazuje_najpozniejszy_znacznik(app):
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam)
        produkcja(50854536, [datetime(2026, 9, 18, 7, 42),
                             datetime(2026, 9, 18, 9, 15)])
        db.session.commit()
        assert _dane(kolumny=['gluing_done_at'])['zamowienia'][0]['pola'][
            'gluing_done_at'] == '18.09.2026 09:15'


def test_zamowienie_nieznane_produkcji_ma_puste_kolumny_produkcyjne(app):
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam)
        db.session.commit()
        assert _dane(kolumny=['gluing_done_at'])['zamowienia'][0]['pola'][
            'gluing_done_at'] == '—'


def test_brak_tabel_produkcji_nie_wywraca_danych(app, monkeypatch):
    import modules.reports.arkusz_service as serwis
    monkeypatch.setattr(serwis, '_jest_tabela', lambda nazwa: False)
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam)
        db.session.commit()
        wynik = _dane(kolumny=['gluing_done_at', 'customer_name'])
        assert wynik['zamowienia'][0]['pola']['gluing_done_at'] == '—'
        assert wynik['zamowienia'][0]['pola']['customer_name'] == 'Jan Przykładowy'


# ===== komorki: tekst i wartosc surowa =================================

def test_wartosci_przychodza_sformatowane_z_serwera(app):
    with app.app_context():
        zam = zamowienie(50854536, paid_amount=Decimal('8704.00'))
        pozycja(zam, objetosc='0.044800')
        db.session.commit()
        wynik = _dane(kolumny=['date_created', 'paid_amount', 'total_volume'])
        zamowienie_json = wynik['zamowienia'][0]
        assert zamowienie_json['pola']['date_created'] == '18.09.2026'
        assert zamowienie_json['pola']['paid_amount'] == '8 704,00'
        assert zamowienie_json['pozycje'][0]['pola']['total_volume'] == '0,044800'


def test_surowe_wartosci_sa_tylko_dla_kolumn_edytowalnych(app):
    with app.app_context():
        zam = zamowienie(50854536, paid_amount=Decimal('8704.00'))
        pozycja(zam)
        db.session.commit()
        zamowienie_json = _dane(kolumny=['date_created', 'paid_amount',
                                         'client_origin'])['zamowienia'][0]
        # paid_amount i client_origin sa edytowalne, date_created nie jest.
        assert zamowienie_json['surowe']['paid_amount'] == '8704.00'
        assert zamowienie_json['surowe']['client_origin'] == 'Stały B2B'
        assert 'date_created' not in zamowienie_json['surowe']


def test_pozycja_bez_identyfikatora_baselinkera_jest_oznaczona(app):
    # Backfill nie przenosil bl_order_product_id, wiec 7938 pozycji
    # historycznych go nie ma. Bez niego setOrderProductFields nie zadziala
    # i kolumny „Ilosc" oraz „Cena brutto" musza byc tylko do odczytu.
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam, bl_pozycja=None)
        pozycja(zam, bl_pozycja=992)
        db.session.commit()
        pozycje = _dane()['zamowienia'][0]['pozycje']
        assert pozycje[0]['bez_id_bl'] is True
        assert pozycje[1]['bez_id_bl'] is False


# ===== endpoint ========================================================

def test_endpoint_oddaje_kolumny_okno_zamowienia_i_podsumowanie(app, klient_http):
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam)
        db.session.commit()
    odpowiedz = klient_http.get('/reports/api/arkusz/dane', query_string=OKNO)
    assert odpowiedz.status_code == 200
    dane = odpowiedz.get_json()
    assert set(dane) == {'kolumny', 'okno', 'zamowienia', 'podsumowanie',
                         'stronicowanie', 'stan_na'}
    # Endpoint oddaje opisy WYBRANYCH kolumn (domyslnie 19 z makiety),
    # nie wszystkich 55. Pelna liste do okienka „Kolumny" serwuje szablon
    # (Zadanie 7), zeby nie wozic jej przy kazdym przewinieciu.
    assert len(dane['kolumny']) == 19
    assert dane['okno']['preset'] == 'wlasne'
    assert dane['okno']['od'] == '2026-09-01'
    assert dane['podsumowanie']['zamowienia'] == 1


def test_wybor_kolumn_zaweza_odpowiedz(app, klient_http):
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam)
        db.session.commit()
    odpowiedz = klient_http.get('/reports/api/arkusz/dane', query_string={
        **OKNO, 'kolumny': 'customer_name,wood_species'})
    dane = odpowiedz.get_json()
    assert [k['nazwa'] for k in dane['kolumny']] == ['customer_name', 'wood_species']
    assert set(dane['zamowienia'][0]['pola']) == {'customer_name'}
    assert set(dane['zamowienia'][0]['pozycje'][0]['pola']) == {'wood_species'}


def test_nieznana_kolumna_konczy_sie_400(klient_http):
    odpowiedz = klient_http.get('/reports/api/arkusz/dane', query_string={
        **OKNO, 'kolumny': 'customer_name,nie_ma_takiej'})
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zla_kolumna'


def test_wymiar_zlozony_jako_kolumna_konczy_sie_400(klient_http):
    # `konfiguracja` jest w rejestrze, ale nie jest kolumna bazy — jej wartosc
    # to krotka trzech kolumn (spec 6.3.2). 400 zamiast 500.
    odpowiedz = klient_http.get('/reports/api/arkusz/dane', query_string={
        **OKNO, 'kolumny': 'konfiguracja'})
    assert odpowiedz.status_code == 400


@pytest.mark.parametrize('szukane', ['przykładowy', 'WP-0912', 'JAN.PRZYKLADOWY@example.com'])
def test_szukajka_dopasowuje_klienta_numer_wewnetrzny_i_mail(app, klient_http, szukane):
    with app.app_context():
        pozycja(zamowienie(50854536))
        inne = zamowienie(50851204, customer_name='Piotr Wzorcowy',
                          internal_order_number='WP-1111', email='piotr.wzorcowy@example.com')
        pozycja(inne, bl_pozycja=993)
        db.session.commit()
    dane = klient_http.get('/reports/api/arkusz/dane',
                           query_string={**OKNO, 'szukaj': szukane}).get_json()
    assert [z['bl_id'] for z in dane['zamowienia']] == [50854536]


def test_szukajka_dopasowuje_pelny_numer_baselinkera(app, klient_http):
    with app.app_context():
        pozycja(zamowienie(50854536))
        pozycja(zamowienie(50851204, customer_name='Piotr'), bl_pozycja=993)
        db.session.commit()
    dane = klient_http.get('/reports/api/arkusz/dane',
                           query_string={**OKNO, 'szukaj': '50851204'}).get_json()
    assert [z['bl_id'] for z in dane['zamowienia']] == [50851204]


def test_szukajka_nie_traktuje_procenta_jak_wieloznacznika(app, klient_http):
    # Bez escapowania „%" wpisane w szukajke zwrocilo by WSZYSTKO, bo LIKE
    # potraktowalby je jako wieloznacznik. Uzytkownik zobaczyłby wyniki
    # dla frazy, ktorej nie ma w danych.
    with app.app_context():
        pozycja(zamowienie(50854536))
        db.session.commit()
    dane = klient_http.get('/reports/api/arkusz/dane',
                           query_string={**OKNO, 'szukaj': '%'}).get_json()
    assert dane['zamowienia'] == []


def test_szukajka_z_cyfra_spoza_ascii_nie_wywala_500(app, klient_http):
    # `str.isdigit()` zwraca True takze dla cyfr Unicode spoza ASCII
    # (Numeric_Type=Digit: „²", „³", „⁵"...), ktorych `int()` nie sparsuje —
    # bez `isascii()` przed sprawdzeniem `_warunek_szukania` rzuca ValueError,
    # ktory leci przez `dane_arkusza` az do Flaska (endpoint nie ma try/except
    # wokol tego wywolania) i konczy sie 500.
    with app.app_context():
        pozycja(zamowienie(50854536))
        db.session.commit()
    odpowiedz = klient_http.get('/reports/api/arkusz/dane',
                                query_string={**OKNO, 'szukaj': '²'})
    assert odpowiedz.status_code == 200
    assert odpowiedz.get_json()['zamowienia'] == []


def test_filtr_zaweza_wynik(app, klient_http):
    with app.app_context():
        pozycja(zamowienie(50854536))
        pozycja(zamowienie(50851204, delivery_state='lubuskie'), bl_pozycja=993)
        db.session.commit()
    dane = klient_http.get('/reports/api/arkusz/dane', query_string={
        **OKNO, 'filtr': 'delivery_state:lubuskie'}).get_json()
    assert [z['bl_id'] for z in dane['zamowienia']] == [50851204]


def test_filtr_po_polu_pozycji_nie_wywala_auto_korelacji(app, klient_http):
    # Regresja: zapytanie stopki (FROM = SalesOrderItem JOIN SalesOrder)
    # dostawalo naraz `warunki_zamowienia(filtr)` (zbudowane pod
    # FROM=SalesOrder) i `warunki_pozycji(filtr)` — SQLAlchemy auto-koreluje
    # wtedy SalesOrder w obu miejscach i rzuca
    # `InvalidRequestError: ... auto-correlation`, czyli 500. Filtr po polu
    # POZIOMU POZYCJI (nie zamówienia, jak wyzej) jest tym, co to wywolywalo —
    # kazdy z siedmiu wymiarow pozycji w rejestrze robil to samo.
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam, gatunek='dąb')
        inny = zamowienie(50851204, dzien=19)
        pozycja(inny, bl_pozycja=993, gatunek='jesion')
        db.session.commit()
    odpowiedz = klient_http.get('/reports/api/arkusz/dane', query_string={
        **OKNO, 'filtr': 'wood_species:dąb'})
    assert odpowiedz.status_code == 200
    dane = odpowiedz.get_json()
    assert [z['bl_id'] for z in dane['zamowienia']] == [50854536]
    assert dane['podsumowanie']['pozycje'] == 1


def test_filtr_poziomu_pozycji_pokazuje_tylko_pasujace_pozycje(app, klient_http):
    # NIEZMIENNIK nr 8: suma w stopce = suma po wierszach na ekranie. Bez
    # filtrowania `zamowienie.items` siatka pokazywala WSZYSTKIE pozycje
    # zamowienia (tu: 2, w tym niepasujaca „jesion"), a stopka tylko
    # pasujace (1) — dwie rozne liczby na tym samym ekranie.
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam, netto='800.00', gatunek='dąb', bl_pozycja=991)
        pozycja(zam, netto='200.00', gatunek='jesion', bl_pozycja=992)
        db.session.commit()
    dane = klient_http.get('/reports/api/arkusz/dane', query_string={
        **OKNO, 'filtr': 'wood_species:dąb'}).get_json()
    assert len(dane['zamowienia']) == 1
    zam_json = dane['zamowienia'][0]
    assert zam_json['wierszy'] == 1
    assert len(zam_json['pozycje']) == 1
    assert zam_json['pozycje'][0]['pola']['value_net'] == '800,00'
    assert dane['podsumowanie']['pozycje'] == 1
    assert dane['podsumowanie']['netto'] == '800,00'


def test_zly_filtr_konczy_sie_400(klient_http):
    odpowiedz = klient_http.get('/reports/api/arkusz/dane',
                                query_string={**OKNO, 'filtr': 'nie_ma_pola:x'})
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zly_filtr'


def test_zle_okno_konczy_sie_400(klient_http):
    odpowiedz = klient_http.get('/reports/api/arkusz/dane',
                                query_string={'od': 'wczoraj', 'do': '2026-09-30'})
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zle_okno'


def test_stronicowanie_liczy_zamowienia_nie_wiersze(app, klient_http):
    # Strona, ktora rozcielaby zamowienie, rozbilaby scalanie przez rowspan.
    with app.app_context():
        for i, bl in enumerate((1, 2, 3)):
            zam = zamowienie(bl, dzien=10 + i)
            for j in range(3):
                pozycja(zam, bl_pozycja=100 * bl + j)
        db.session.commit()
    dane = klient_http.get('/reports/api/arkusz/dane',
                           query_string={**OKNO, 'limit': 2}).get_json()
    assert len(dane['zamowienia']) == 2
    assert sum(z['wierszy'] for z in dane['zamowienia']) == 6
    assert dane['stronicowanie'] == {'offset': 0, 'limit': 2,
                                     'zamowien_lacznie': 3, 'wiecej': True}


@pytest.mark.parametrize('argumenty, oczekiwane', [
    ({'offset': '-5'}, (0, 200)),
    ({'limit': '0'}, (0, 1)),
    ({'limit': '99999'}, (0, 500)),
    ({'offset': 'abc', 'limit': 'xyz'}, (0, 200)),
    # Python `int` jest nieograniczony — bez gornej granicy taka wartosc
    # trafilaby wprost do `LIMIT ..., ...` i MySQL odrzucilby zapytanie
    # bledem 1064 (poza zakresem BIGINT) = 500. SQLite tego nie zlapie
    # (stad ten test tylko na przycinanie), wiec 500 na prawdziwym MySQL-u
    # wymaga osobnej, recznej weryfikacji na kontenerze `db`.
    ({'offset': '99999999999999999999999'}, (10**9, 200)),
])
def test_absurdalne_stronicowanie_jest_przycinane(klient_http, argumenty, oczekiwane):
    dane = klient_http.get('/reports/api/arkusz/dane',
                           query_string={**OKNO, **argumenty}).get_json()
    assert (dane['stronicowanie']['offset'], dane['stronicowanie']['limit']) == oczekiwane


def test_podsumowanie_liczy_cale_okno_a_nie_strone(app, klient_http):
    # NIEZMIENNIK MIEDZYPANELOWY. Stopka pokazuje sumy calego okna dat,
    # a siatka jedna strone. Bez tego testu rozjazd wyszedlby dopiero
    # u uzytkownika, ktory zsumuje kolumne w glowie i porowna ze stopka.
    with app.app_context():
        for bl in (1, 2, 3):
            pozycja(zamowienie(bl, dzien=10 + bl), netto='800.00',
                    objetosc='0.010000', bl_pozycja=bl)
        db.session.commit()

    def na_liczbe(tekst):
        return Decimal(tekst.replace(' ', '').replace(' ', '').replace(',', '.'))

    strona = klient_http.get('/reports/api/arkusz/dane',
                             query_string={**OKNO, 'limit': 1}).get_json()
    assert len(strona['zamowienia']) == 1
    assert strona['podsumowanie'] == {'zamowienia': 3, 'pozycje': 3,
                                      'netto': '2 400,00', 'objetosc': '0,030000'}

    wszystko = klient_http.get('/reports/api/arkusz/dane',
                               query_string={**OKNO, 'limit': 500}).get_json()
    assert wszystko['podsumowanie'] == strona['podsumowanie']
    # Suma tego, co widac na ekranie, musi sie zgadzac ze stopka, gdy
    # wszystkie strony sa doczytane. Ten warunek laczy dwa niezalezne
    # zapytania (strona i agregat) i zaden test pojedynczej funkcji go nie widzi.
    suma_z_wierszy = sum(na_liczbe(z['pozycje'][0]['pola']['value_net'])
                         for z in wszystko['zamowienia'])
    assert suma_z_wierszy == na_liczbe(wszystko['podsumowanie']['netto'])


def test_endpoint_zwraca_json_przy_wygaslej_sesji(klient_http):
    with klient_http.session_transaction() as sesja:
        sesja.clear()
    odpowiedz = klient_http.get('/reports/api/arkusz/dane', query_string=OKNO)
    assert odpowiedz.status_code == 401
    assert odpowiedz.get_json() == {'error': 'unauthorized'}


def test_kolumny_z_adresu_bez_parametru_daja_zestaw_domyslny(app):
    from modules.reports.arkusz_service import KOLUMNY_DOMYSLNE
    with app.app_context():
        assert kolumny_z_adresu(None) == list(KOLUMNY_DOMYSLNE)
        assert kolumny_z_adresu('  ') == list(KOLUMNY_DOMYSLNE)


# ===== poprawka z przegladu Zadania 8 [WAZNE] ============================

def test_numer_zamowienia_bl_w_danych_siatki_bez_spacji_tysiecznych(app):
    # baselinker_order_id jest w modelu db.Integer — bez wyjatku w
    # _typ_kolumny dostaje typ 'liczba' i formatuj_liczbe(v, 0) doklada
    # spacje co trzy cyfry ('50 854 536'), niezgodnie z tym, co uzytkownik
    # widzi w BaseLinkerze i co da sie stamtad skopiowac.
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam)
        db.session.commit()
        pola = _dane(kolumny=['baselinker_order_id'])['zamowienia'][0]['pola']
        assert pola['baselinker_order_id'] == '50854536'


# ===== EKSPORT (Zadanie 15) ============================================

def test_eksport_csv_ma_bom_i_srednik(app, klient_http):
    # Excel po polsku czyta CSV ze srednikiem, a bez BOM-u kaleczy polskie
    # znaki. Ta sama konwencja, co w eksporcie widoku Eksploratora.
    with app.app_context():
        pozycja(zamowienie(50854536))
        db.session.commit()
    odpowiedz = klient_http.get('/reports/api/arkusz/eksport', query_string=OKNO)
    assert odpowiedz.status_code == 200
    assert odpowiedz.mimetype == 'text/csv'
    tresc = odpowiedz.get_data(as_text=True)
    assert tresc.startswith('﻿')
    assert ';' in tresc.splitlines()[0]


def test_eksport_csv_ma_naglowki_z_etykiet_wybranych_kolumn(app, klient_http):
    with app.app_context():
        pozycja(zamowienie(50854536))
        db.session.commit()
    tresc = klient_http.get('/reports/api/arkusz/eksport', query_string={
        **OKNO, 'kolumny': 'customer_name,wood_species'}).get_data(as_text=True)
    assert tresc.splitlines()[0].lstrip('﻿') == 'Klient;Gatunek'


def test_eksport_csv_ma_wiersz_na_pozycje_z_powtorzonym_polem_zamowienia(app, klient_http):
    # Scalanie komorek to sprawa EKRANU. W pliku kazdy wiersz musi byc
    # kompletny, inaczej filtr w Excelu pokaze puste komorki klienta.
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam, gatunek='dąb')
        pozycja(zam, gatunek='buk', bl_pozycja=992)
        db.session.commit()
    linie = klient_http.get('/reports/api/arkusz/eksport', query_string={
        **OKNO, 'kolumny': 'customer_name,wood_species'}).get_data(as_text=True).splitlines()
    assert linie[1:] == ['Jan Przykładowy;dąb', 'Jan Przykładowy;buk']


def test_eksport_csv_respektuje_szukajke_i_filtr(app, klient_http):
    with app.app_context():
        pozycja(zamowienie(50854536))
        pozycja(zamowienie(50851204, customer_name='Piotr Wzorcowy'), bl_pozycja=993)
        db.session.commit()
    tresc = klient_http.get('/reports/api/arkusz/eksport', query_string={
        **OKNO, 'kolumny': 'customer_name', 'szukaj': 'wzorcowy'}).get_data(as_text=True)
    assert 'Piotr Wzorcowy' in tresc
    assert 'Jan Przykładowy' not in tresc


def test_eksport_csv_nie_stronicuje(app, klient_http):
    # Stronicowanie dotyczy ekranu. Plik ma zawierac cale okno dat, nawet
    # gdy przekracza limit strony.
    with app.app_context():
        for bl in range(1, 6):
            pozycja(zamowienie(bl, dzien=10), bl_pozycja=bl)
        db.session.commit()
    linie = klient_http.get('/reports/api/arkusz/eksport', query_string={
        **OKNO, 'kolumny': 'customer_name', 'limit': 1}).get_data(as_text=True).splitlines()
    assert len(linie) == 6      # naglowek + piec pozycji


def test_eksport_csv_odrzuca_zle_okno(klient_http):
    odpowiedz = klient_http.get('/reports/api/arkusz/eksport',
                                query_string={'od': 'wczoraj', 'do': '2026-09-30'})
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zle_okno'


# ===== poprawki z przegladu fali 3 (arkusz i eksport) ====================

def test_sformatuj_wymiary_slownikowe_uzywaja_tej_samej_mapy_etykiet_co_reszta_zakladki():
    # NIEZMIENNIK MIEDZYEKRANOWY (przeglad fali 3, [KRYTYCZNE] 1): order_source
    # jest podpisany „Sklep" na dashboardzie i w filtrach — obie sciezki
    # przechodza przez `analiza_service._etykieta_wartosci` +
    # `ETYKIETY_WARTOSCI`. Arkusz mial WLASNA sciezke formatowania
    # (`sformatuj`), ktora nie znala tej mapy w ogole, wiec siatka i eksport
    # CSV arkusza pokazywaly surowy kod z BaseLinkera ("shop") — TA SAMA
    # WARTOSC POD DWIEMA NAZWAMI, po raz czwarty w tym projekcie. Test
    # przechodzi WSZYSTKIE wpisy ETYKIETY_WARTOSCI (nie tylko order_source)
    # i dowodzi, ze `arkusz_service.sformatuj` oddaje DOKLADNIE to samo, co
    # `_etykieta_wartosci` uzywana przez dashboard i filtry.
    from modules.reports.analiza_service import ETYKIETY_WARTOSCI, _etykieta_wartosci
    from modules.reports.arkusz_service import sformatuj
    for nazwa, slownik in ETYKIETY_WARTOSCI.items():
        for surowa_wartosc, oczekiwana_etykieta in slownik.items():
            assert sformatuj(surowa_wartosc, 'tekst', nazwa) == oczekiwana_etykieta
            assert (sformatuj(surowa_wartosc, 'tekst', nazwa)
                    == _etykieta_wartosci(nazwa, surowa_wartosc))


def test_order_source_pokazuje_etykiete_nie_surowy_kod_w_siatce(app):
    # [KRYTYCZNE] 1, dowod na pelnej sciezce `dane_arkusza`: siatka arkusza
    # pokazywala surowe „shop" zamiast „Sklep" (etykieta z dashboardu/filtrow,
    # ETYKIETY_WARTOSCI['order_source']).
    with app.app_context():
        zam = zamowienie(50854536, order_source='shop')
        pozycja(zam)
        db.session.commit()
        pola = _dane(kolumny=['order_source'])['zamowienia'][0]['pola']
        assert pola['order_source'] == 'Sklep'
        assert pola['order_source'] != 'shop'


def test_eksport_csv_pokazuje_etykiete_order_source_nie_surowy_kod(app, klient_http):
    # [KRYTYCZNE] 1, ta sama pulapka w eksporcie CSV — `wiersze_eksportu`
    # reuzywa `sformatuj`, wiec fix w jednym miejscu naprawia oba ekrany.
    with app.app_context():
        pozycja(zamowienie(50854536, order_source='shop'))
        db.session.commit()
    tresc = klient_http.get('/reports/api/arkusz/eksport', query_string={
        **OKNO, 'kolumny': 'order_source'}).get_data(as_text=True)
    linie = tresc.splitlines()
    assert linie[1] == 'Sklep'
    assert 'shop' not in tresc.lower()


def test_eksport_csv_liczby_nie_maja_spacji_tysiecznej(app, klient_http):
    # [WAZNE] 2: eksport reuzywal `sformatuj` EKRANOWE, ze spacja jako
    # separatorem tysiecy ("12 345,67") — Excel i Arkusze Google wczytuja
    # taka komorke jako TEKST, nie liczbe (nie da sie zsumowac). Separator
    # dziesietny zostaje PRZECINKIEM: eksport idzie srednikiem
    # (routers_analiza.py, csv.writer(delimiter=';')), czyli polskim
    # ustawieniem regionalnym Excela, ktore i tak oczekuje przecinka —
    # kropka wprowadzalaby NOWA niezgodnosc zamiast naprawiac stara.
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam, netto='12345.67')
        db.session.commit()
    tresc = klient_http.get('/reports/api/arkusz/eksport', query_string={
        **OKNO, 'kolumny': 'value_net'}).get_data(as_text=True)
    linie = tresc.splitlines()
    assert linie[1] == '12345,67'
    assert ' ' not in linie[1]


def test_siatka_na_ekranie_dalej_ma_spacje_tysieczna(app):
    # Uzupelnienie powyzszego: zmiana dotyczy WYLACZNIE eksportu CSV — ekran
    # (`dane_arkusza` bez `eksport=True`) ma zostac przy dotychczasowym,
    # polskim formacie ze spacja (formatuj_liczbe), zeby nie zlamac
    # `test_wartosci_przychodza_sformatowane_z_serwera` i innych, ktore juz
    # tego formatu pilnuja.
    with app.app_context():
        zam = zamowienie(50854536)
        pozycja(zam, netto='12345.67')
        db.session.commit()
        pola = _dane(kolumny=['value_net'])['zamowienia'][0]['pozycje'][0]['pola']
        assert pola['value_net'] == '12 345,67'


@pytest.mark.parametrize('typ, wartosc, oczekiwane', [
    ('kwota', Decimal('12345.67'), '12345,67'),
    ('objetosc', Decimal('1234.500000'), '1234,500000'),
    ('liczba', Decimal('12345'), '12345'),
])
def test_sformatuj_eksport_usuwa_spacje_ale_zostawia_polski_przecinek(typ, wartosc, oczekiwane):
    # Jednostkowy dowod dla wszystkich trzech typow liczbowych naraz —
    # nie tylko 'kwota' z testu przez API wyzej.
    from modules.reports.arkusz_service import sformatuj
    assert sformatuj(wartosc, typ, eksport=True) == oczekiwane


def test_podpowiedz_zaplacono_opisuje_prawdziwe_zachowanie_zapisu():
    # [WAZNE] 6: tekst mowil „wysylamy przeliczona na brutto, jesli
    # zamowienie ma typ ceny brutto ALBO NIE MA GO WCALE" — nieaktualne od
    # 554ac3a: dzis brak oznaczonego typu ceny KONCZY SIE ODMOWA zapisu
    # (BladBaselinkera w modules/reports/bl_zapis.py, `_platnosc_brutto`),
    # nie domyslnym przeliczeniem. Podpowiedz klamala uzytkownikowi
    # o rzeczywistym zachowaniu.
    from modules.reports.arkusz_service import kolumna_arkusza
    podpowiedz = kolumna_arkusza('paid_amount')['podpowiedz']
    assert 'albo nie ma go wcale' not in podpowiedz
    assert 'ODRZUCA' in podpowiedz or 'odrzuca' in podpowiedz


def test_eksport_csv_puste_komorki_sa_puste_nie_polpauza(app, klient_http):
    # ZNALEZISKO z przegladu: na EKRANIE pusta komorka to „—"
    # (arkusz_service.PUSTA_KOMORKA), ale w pliku CSV musi zostac pusta
    # komorka — inaczej Excel traktuje „—" jak zwykla wartosc tekstowa:
    # autofiltr wystawia ja jako osobna pozycje w kazdej kolumnie, a kolumny
    # liczbowe/datowe z brakami (tu: payment_date) przestaja byc liczbami —
    # SUMA, tabela przestawna i sortowanie po nich milczaco nie dzialaja.
    with app.app_context():
        zam = zamowienie(50854536)  # payment_date nie ustawione -> None
        pozycja(zam)
        db.session.commit()
    tresc = klient_http.get('/reports/api/arkusz/eksport', query_string={
        **OKNO, 'kolumny': 'customer_name,payment_date'}).get_data(as_text=True)
    linie = tresc.splitlines()
    assert linie[1] == 'Jan Przykładowy;'
    assert '—' not in tresc
