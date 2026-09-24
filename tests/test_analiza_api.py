# -*- coding: utf-8 -*-
"""GET /reports/api/analytics — jedno zadanie, komplet danych dashboardu.

Testy pilnuja czterech rzeczy:
1. Kontraktu payloadu — front podmienia wartosci w gotowym szkielecie, wiec
   brakujacy klucz nie wywali sie glosno, tylko zostawi pusta karte.
2. Regresji na powielone saldo: endpoint musi oddac saldo policzone RAZ na
   zamowienie. Na produkcji sumowanie po pozycjach zawyzalo je 7,58x.
3. Walidacji wymiaru — nazwa spoza rejestru pol ma dac 400, nie 500
   z AttributeError w srodku getattr(SalesOrder, nazwa). Od Planu D wymiar
   karty jest czescia ZAPISANEGO ukladu, a nie adresu, wiec ta walidacja
   siedzi w `POST /reports/api/uklad`; stare `?kanal=` jest ignorowane.
4. Serializacji: Decimal nie jest serializowalny przez jsonify, wiec kazda
   kwota musi wyjsc jako liczba.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports.analiza_service import (
    dane_dashboardu, do_json, poprzedni_okres, zmiana_procentowa,
)
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.reports.models_uklad import UkladDashboardu
from modules.reports.uklad import KATALOG, UKLAD_DOMYSLNY, Instancja
from modules.reports import reports_bp  # rejestracja blueprintu = te same URL-e co na produkcji
import modules.reports.routers_analiza  # noqa: F401 — dopisuje trasy do reports_bp

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
# prod_orders jest po drugiej stronie lejka wycen (stopien „W realizacji"),
# wiec tabela MUSI istniec w bazie testowej — inaczej kazdy test dotykajacy
# /api/analytics wywala sie na „no such table: prod_orders".
# `prod_orders.shipping_label_base64` jest kolumna typu LONGTEXT (dialekt
# MySQL), a SQLite nie umie takiej skompilowac — `create_all` wywala sie
# CompileError, zanim ruszy pierwszy test. Uczymy wiec kompilator SQLite
# czytac LONGTEXT jako TEXT. Szim jest TESTOWY: na produkcji kolumna ma
# zostac LONGTEXT-em, bo trzyma etykiete kurierska w base64.
@compiles(LONGTEXT, 'sqlite')
def _longtext_jako_text(typ, kompilator, **kw):
    return 'TEXT'

from modules.production.models import ProductionOrder  # noqa: F401 — rejestr mapperów
from modules.users.models import User  # noqa: F401 — rejestr mapperów
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów
from modules.quotes.models import QuoteStatus

_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    SalesClient, SalesOrder, SalesOrderItem, ProductionOrder,
    # Od Planu D /api/analytics i /analiza czytaja uklad uzytkownika z bazy.
    UkladDashboardu,
)]

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATYKA_PRODUKCJI = os.path.join(KORZEN, 'modules', 'production', 'static')


@pytest.fixture()
def app(monkeypatch):
    # Bramka uprawnien jest przedmiotem Zadania 14 — tutaj ja wylaczamy, zeby
    # test sprawdzal KONTRAKT DANYCH, a nie kontrole dostepu. Podmieniamy sam
    # PermissionService, bo dekorator rozstrzyga dostep przez niego.
    from modules.users.services.permission_service import PermissionService
    monkeypatch.setattr(PermissionService, 'user_has_module_access',
                        staticmethod(lambda user_id, module_key: True))

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(reports_bp)
    # Trasa HTML 'analiza' (test_zly_filtr_porownania_nie_wywala_strony) renderuje
    # PRAWDZIWY dashboard.html, ktory wola {% include 'sidebar/sidebar.html' %}
    # i url_for('production.static', ...) po Chart.js. Ten sam gotcha i to samo
    # rozwiazanie co w tests/test_analiza_widok.py.
    produkcja = Blueprint('production', __name__, static_folder=STATYKA_PRODUKCJI,
                          static_url_path='/production/static')
    app.register_blueprint(produkcja, url_prefix='/production')
    app.jinja_loader = ChoiceLoader([
        DictLoader({'sidebar/sidebar.html': '<nav data-sidebar-zaslepka></nav>'}),
        app.jinja_loader,
    ])
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        db.session.add(User(email='kontroler@woodpower.pl', password='x',
                            role='admin', active=True))
        db.session.commit()
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    c = app.test_client()
    with c.session_transaction() as sesja:
        sesja['user_email'] = 'kontroler@woodpower.pl'
    return c


def klucz_karty(typ, wymiar=None):
    """Klucz karty w payloadzie. Od Planu D karty sa kluczowane INSTANCJA
    (`typ:wymiar`), bo ten sam typ moze stac na pulpicie kilka razy — takze
    obie karty kubelkowe, ktore wczesniej byly kluczami najwyzszego poziomu."""
    return Instancja(typ, wymiar or KATALOG[typ].domyslny_wymiar).klucz


def _uklad(client, *instancje):
    """Zapisuje uklad przez endpoint. Od Planu D wymiar karty jest czescia
    ZAPISANEGO ukladu, a nie adresu — `?kanal=caretaker` jest ignorowane."""
    odpowiedz = client.post('/reports/api/uklad', json={'uklad': [
        {'typ': typ, 'wymiar': wymiar} for typ, wymiar in instancje]})
    assert odpowiedz.status_code == 200, odpowiedz.get_json()


# Karta naleznosci w swoim wymiarze domyslnym. Od partii E (punkt E1) nie ma
# jej w UKLADZIE DOMYSLNYM — testy tej karty stawiaja ja na pulpicie same,
# tak jak zrobi to uzytkownik przez „+ Dodaj statystyke".
NALEZNOSCI = ('naleznosci', 'wiek_zamowienia')


def _zamowienie(bl_id, dzien, pozycje, saldo='0', kanal='shop',
                opiekun='Łukasz Próbny', client_id=None):
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien,
                     balance_due=Decimal(saldo), order_source=kanal,
                     caretaker=opiekun, current_status='Nowe',
                     delivery_method='Kurier', delivery_cost=Decimal('100.00'),
                     client_id=client_id)
    db.session.add(zam)
    db.session.flush()
    for netto, objetosc, grupa in pozycje:
        # technology i wood_class sa tu po to, zeby wymiar zlozony
        # `konfiguracja` (Zadanie 1) mial z czego zbudowac etykiete.
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal(netto), total_volume=Decimal(objetosc),
            group_type=grupa, wood_species='dąb', technology='lity',
            wood_class='A/B', finish_state='surowy', quantity=1))
    return zam


# --- funkcje czyste ---------------------------------------------------------

def test_poprzedni_okres_ma_te_sama_dlugosc_i_konczy_sie_dzien_przed():
    # 1-21 wrzesnia to 21 dni. Poprzednie 21 dni koncza sie 31 sierpnia,
    # wiec zaczynaja sie 11 sierpnia — 12 sierpnia dalby okres 20-dniowy
    # i zlamal niezmiennik z nazwy tego testu.
    od_p, do_p = poprzedni_okres(date(2026, 9, 1), date(2026, 9, 21))
    assert (od_p, do_p) == (date(2026, 8, 11), date(2026, 8, 31))
    assert (do_p - od_p).days == (date(2026, 9, 21) - date(2026, 9, 1)).days


def test_poprzedni_okres_dla_jednego_dnia():
    assert poprzedni_okres(date(2026, 9, 5), date(2026, 9, 5)) == (
        date(2026, 9, 4), date(2026, 9, 4))


def test_zmiana_procentowa_przy_zerowej_bazie_jest_nieokreslona():
    """Wzrost z zera to nie 'plus nieskonczonosc' — karta ma pokazac kreske."""
    assert zmiana_procentowa(Decimal('100'), Decimal('0')) is None
    assert zmiana_procentowa(Decimal('0'), Decimal('0')) is None


def test_zmiana_procentowa_liczy_w_obie_strony():
    assert zmiana_procentowa(Decimal('92.4'), Decimal('100')) == Decimal('-7.6')
    assert zmiana_procentowa(Decimal('105.2'), Decimal('100')) == Decimal('5.2')


def test_do_json_zamienia_decimal_i_date():
    wynik = do_json({'kwota': Decimal('12.34'), 'dzien': date(2026, 9, 1),
                     'lista': [Decimal('1')], 'nic': None})
    assert wynik == {'kwota': 12.34, 'dzien': '2026-09-01', 'lista': [1.0], 'nic': None}


# --- kontrakt payloadu ------------------------------------------------------

def test_payload_ma_komplet_kluczy(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('1000.00', '0.50', 'towar')], saldo='200.00')
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()

    # Od Planu D „klienci" i „naleznosci" mieszkaja w `karty` pod kluczem
    # instancji, a `pominietych` mowi, ile pozycji zapisanego ukladu odpadlo.
    # `wykluczenia` (partia E, punkt E4): stan pol wykluczen pozycji — jest
    # zawsze, takze bez wykluczen (wtedy z pustymi napisami).
    assert set(dane) == {
        'okres', 'kpi', 'trend', 'karty', 'kanal_rozbicie',
        'lejek', 'dostawa_koszt_kuriera', 'wymiary_dostepne',
        'wnioski', 'segmenty', 'porownanie', 'jednostki', 'pominietych',
        'wykluczenia', 'etykiety_miar',
        # Przelacznik „zl / szt. / zl + szt." kazdego kafelka (24.09.2026).
        'przelaczniki',
    }
    # Bez segmentu porownawczego (Zadanie 10) na pasku jest sam chip bazowy.
    assert [s['id'] for s in dane['segmenty']] == ['baza']
    assert dane['porownanie'] is None
    assert set(dane['karty']) == {i.klucz for i in UKLAD_DOMYSLNY
                                  if KATALOG[i.typ].wymiarowy}
    # Asercja po kluczach, nie przez rownosc calego slownika: Zadanie 8 dolozy
    # do `okres` opis po polsku i rownosc padlaby bez powodu merytorycznego.
    assert dane['okres']['od'] == '2026-09-01'
    assert dane['okres']['do'] == '2026-09-21'
    assert len(dane['okres']['stan_na']) == 5  # HH:MM


def test_kpi_ma_piec_liczb_i_komplet_zmian(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('1000.00', '0.50', 'towar')])
        _zamowienie(2, date(2026, 8, 20), [('2000.00', '1.00', 'towar')])
        db.session.commit()

    kpi_ = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()['kpi']

    assert kpi_['netto'] == 1000.0
    assert kpi_['objetosc'] == 0.5
    assert kpi_['zamowienia'] == 1
    assert kpi_['srednie_zamowienie'] == 1000.0
    assert kpi_['cena_za_m3'] == 2000.0
    # `sztuki` (24.09.2026): sztuki produktow dla przelacznika kafelka KPI.
    assert set(kpi_['zmiana']) == {'netto', 'objetosc', 'sztuki', 'zamowienia',
                                   'srednie_zamowienie', 'cena_za_m3'}
    assert kpi_['zmiana']['netto'] == -50.0   # 1000 wobec 2000 w poprzednim okresie


def test_saldo_nie_jest_mnozone_przez_liczbe_pozycji(client, app):
    """Regresja na blad 7,58x z poprzednika."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.01', 'towar')] * 34,
                    saldo='9969.32')
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()

    assert dane['kpi']['saldo'] == 9969.32


def test_objetosc_w_kpi_wyklucza_uslugi(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3),
                    [('1000.00', '2.50', 'towar'), ('800.00', '88.00', 'usługa')])
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()

    assert dane['kpi']['objetosc'] == 2.5
    assert dane['kpi']['netto'] == 1800.0


def test_karta_ma_wymiar_etykiete_i_udzialy(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('750.00', '0.50', 'towar')], kanal='shop')
        _zamowienie(2, date(2026, 9, 4), [('250.00', '0.20', 'towar')], kanal='allegro')
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('kanal')]

    assert karta['wymiar'] == 'order_source'
    assert karta['etykieta'] == 'Kanał sprzedaży'
    # Surowy kod BaseLinkera zostaje w `wartosc` — to on jedzie do filtra
    # i do Eksploratora. Po polsku jest wylacznie `etykieta`.
    assert [w['wartosc'] for w in karta['wiersze']] == ['shop', 'allegro']
    assert [w['etykieta'] for w in karta['wiersze']] == ['Sklep', 'Allegro']
    assert [w['udzial'] for w in karta['wiersze']] == [75.0, 25.0]


def test_pusta_wartosc_wymiaru_dostaje_czytelna_etykiete(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')], kanal=None)
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('kanal')]

    assert karta['wiersze'][0]['etykieta'] == '(brak)'


def test_trend_ma_oba_lata_i_dwanascie_etykiet_miesiecy(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('1000.00', '0.50', 'towar')])
        _zamowienie(2, date(2025, 9, 3), [('800.00', '0.40', 'towar')])
        db.session.commit()

    trend = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()['trend']

    assert trend['etykiety'] == ['STY', 'LUT', 'MAR', 'KWI', 'MAJ', 'CZE', 'LIP', 'SIE', 'WRZ']
    assert len(trend['biezacy']) == 9 and len(trend['poprzedni']) == 9
    assert trend['biezacy'][-1]['netto'] == 1000.0
    assert trend['poprzedni'][-1]['netto'] == 800.0


def test_naleznosci_maja_etykiety_kubelkow_z_makiety(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 1, 5), [('100.00', '0.10', 'towar')], saldo='500.00')
        db.session.commit()
        db.session.query(SalesOrder).update({'current_status': 'W produkcji — surowe'})
        db.session.commit()

    _uklad(client, NALEZNOSCI)
    naleznosci = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                       .get_json()['karty'][klucz_karty('naleznosci')]

    assert [k['kubelek'] for k in naleznosci['kubelki']] == [
        '0–14 dni', '15–30', '31–60', '61–90', '>90']


def test_ostrzezenie_liczy_tylko_stare_zamowienia_w_produkcji(client, app):
    """Asercja na WARTOSC, nie na `>= 0` — licznik jest int(... or 0), wiec
    warunek nieujemnosci nie moze byc falszywy i niczego by nie sprawdzil.

    Daty WZGLEDEM dnia, od ktorego liczy karta (`dzis_lokalnie()`, prog 90
    dni). „Swieze" zamowienie mialo date 20.09.2026 na sztywno, wiec od
    20.12.2026 samo robilo sie stare i test oblewal (kontrola ostatnich
    poprawek, DROBNE 2)."""
    from modules.reports.analiza_service import dzis_lokalnie
    dzis = dzis_lokalnie()
    with app.app_context():
        stare_w_produkcji = _zamowienie(1, dzis - timedelta(days=120),
                                        [('100.00', '0.10', 'towar')], saldo='500.00')
        stare_inny_status = _zamowienie(2, dzis - timedelta(days=119),
                                        [('100.00', '0.10', 'towar')], saldo='300.00')
        swieze_w_produkcji = _zamowienie(3, dzis - timedelta(days=4),
                                         [('100.00', '0.10', 'towar')], saldo='900.00')
        db.session.commit()
        stare_w_produkcji.current_status = 'W produkcji — surowe'
        stare_inny_status.current_status = 'Nowe — opłacone'
        swieze_w_produkcji.current_status = 'W produkcji — surowe'
        db.session.commit()

    _uklad(client, NALEZNOSCI)
    ostrzezenie = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                        .get_json()['karty'][klucz_karty('naleznosci')]['ostrzezenie']

    assert ostrzezenie['zamowienia'] == 1
    assert ostrzezenie['saldo'] == 500.0


def test_naleznosci_niosa_nadplaty_jako_osobna_pozycje(client, app):
    """Nadplaty (saldo ujemne) sa OSOBNA pozycja karty, nie szostym kubelkiem
    wieku — patrz komentarz przy aggregates.nadplaty. Zamowienie z nadplata
    nie ma wchodzic do zadnego z pieciu kubelkow."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')], saldo='-250.50')
        _zamowienie(2, date(2026, 9, 4), [('100.00', '0.10', 'towar')], saldo='400.00')
        db.session.commit()

    _uklad(client, NALEZNOSCI)
    naleznosci = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                       .get_json()['karty'][klucz_karty('naleznosci')]

    assert naleznosci['nadplaty'] == {'zamowienia': 1, 'saldo': 250.5}
    assert sum(k['zamowienia'] for k in naleznosci['kubelki']) == 1


def test_niezmiennik_naleznosci_minus_nadplaty_rowna_sie_kpi_saldo(client, app):
    """Ta sama tozsamosc co w test_sales_aggregates, ale przez PELNY payload
    endpointu: suma kubelkow karty 'Naleznosci' minus jej 'nadplaty' ma dac
    dokladnie kpi['saldo'] z paska KPI. To klasa bledu, ktorej test pojedynczej
    karty nie widzi — kazda karta osobno moze wygladac poprawnie, a mimo to
    dwie liczby na jednym ekranie sie nie zgadzac.
    """
    with app.app_context():
        _zamowienie(1, date(2026, 9, 1), [('1000.00', '0.10', 'towar')], saldo='1000.00')
        _zamowienie(2, date(2026, 9, 2), [('5000.00', '0.20', 'towar')], saldo='5000.00')
        _zamowienie(3, date(2026, 9, 3), [('300.00', '0.05', 'towar')], saldo='-800.00')
        _zamowienie(4, date(2026, 9, 4), [('120.00', '0.02', 'towar')], saldo='-60.82')
        db.session.commit()

    _uklad(client, ('kpi', None), NALEZNOSCI)
    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()

    naleznosci = dane['karty'][klucz_karty('naleznosci')]
    suma_kubelkow = sum(k['saldo'] for k in naleznosci['kubelki'])
    nadplaty = naleznosci['nadplaty']

    assert nadplaty['zamowienia'] == 2
    assert nadplaty['saldo'] == pytest.approx(860.82)
    assert suma_kubelkow - nadplaty['saldo'] == pytest.approx(dane['kpi']['saldo'])


def test_rozbicie_kanalu_recznego_pomija_pozostale_kanaly(client, app):
    """Naglowek karty mowi „Wewnatrz kanalu recznego", wiec zamowienie ze sklepu
    nie ma tam wejsc — nawet jesli ma wypelniony client_origin."""
    with app.app_context():
        reczne = _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')],
                             kanal='personal')
        sklepowe = _zamowienie(2, date(2026, 9, 4), [('900.00', '0.90', 'towar')],
                               kanal='shop')
        db.session.commit()
        reczne.client_origin = 'Stały B2B'
        sklepowe.client_origin = 'Detal'
        db.session.commit()

    rozbicie = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                     .get_json()['kanal_rozbicie']

    assert [w['etykieta'] for w in rozbicie['wiersze']] == ['Stały B2B']
    assert rozbicie['wiersze'][0]['netto'] == 300.0


def test_wartosci_logiczne_dostaja_polskie_etykiety(client, app):
    """MySQL odda TINYINT 0/1, SQLite True/False — uzytkownik ma zobaczyc
    „Tak" i „Nie", a nie surowa reprezentacje dialektu."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')])
        db.session.commit()
    _uklad(client, ('kanal', 'own_transport'))

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('kanal', 'own_transport')]

    assert karta['wiersze'][0]['etykieta'] in ('Tak', 'Nie')


def test_nieznana_wartosc_wymiaru_zostaje_doslownie(client, app):
    """Mapa etykiet nie jest filtrem: kanal, ktorego nikt nie przewidzial,
    ma sie pokazac taki, jaki jest."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')], kanal='erli')
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('kanal')]

    assert karta['wiersze'][0]['etykieta'] == 'erli'


def test_karta_miksu_grupuje_po_wymiarze_zlozonym(client, app):
    """Domyslny wymiar karty to `konfiguracja` z Zadania 1, a etykieta wiersza
    to trzy skladowe sklejone srodkowa kropka."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')])
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('mix')]

    assert karta['wymiar'] == 'konfiguracja'
    assert karta['etykieta'] == 'Gatunek · technologia · klasa'
    assert karta['wiersze'][0]['etykieta'] == 'dąb · lity · A/B'
    # `wartosc` wymiaru zlozonego to lista skladowych (krotka po serializacji).
    assert karta['wiersze'][0]['wartosc'] == ['dąb', 'lity', 'A/B']


def test_wiersz_zbiorczy_jest_oznaczony_a_pusta_wartosc_nie(client, app):
    """Oba maja `wartosc = None`. Bez znacznika `zbiorczy` nie da sie ich
    rozroznic, a Zadanie 10 musi — inaczej „Pozostale (7)" bazy zlaczyloby sie
    z wierszem „(brak)" segmentu porownawczego."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('900.00', '0.90', 'towar')], kanal=None)
        for i in range(6):
            _zamowienie(i + 2, date(2026, 9, 4), [(f'{100 - i}.00', '0.10', 'towar')],
                        kanal=f'kanal{i}')
        db.session.commit()

    wiersze = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                    .get_json()['karty'][klucz_karty('kanal')]['wiersze']

    pusty = [w for w in wiersze if w['etykieta'] == '(brak)'][0]
    zbiorczy = [w for w in wiersze if w['etykieta'].startswith('Pozostałe')][0]
    assert pusty['wartosc'] is None and pusty['zbiorczy'] is False
    assert zbiorczy['wartosc'] is None and zbiorczy['zbiorczy'] is True


def test_karta_miesci_sie_w_limicie_razem_z_wierszem_zbiorczym(client, app):
    """Limit karty opiekunow to piec wierszy LACZNIE — makieta pokazuje cztery
    nazwiska plus „Partnerzy (7)", nie piec nazwisk i szosty wiersz."""
    with app.app_context():
        for i in range(9):
            _zamowienie(i + 1, date(2026, 9, 3),
                        [(f'{900 - i * 100}.00', '0.10', 'towar')],
                        opiekun=f'Opiekun {i}')
        db.session.commit()

    wiersze = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                    .get_json()['karty'][klucz_karty('opiekun')]['wiersze']

    assert len(wiersze) == 5
    assert wiersze[-1]['etykieta'] == 'Pozostałe (5)'


def test_najlepsze_srednie_liczy_sie_na_serwerze_przed_zwinieciem_ogona(client, app):
    """Przegladarka liczyla to na wierszach JUZ ZWINIETYCH i potrafila wskazac
    syntetyczny wiersz „Pozostale (N)" jako najlepszego handlowca."""
    with app.app_context():
        for i in range(6):
            _zamowienie(i + 1, date(2026, 9, 3),
                        [(f'{600 - i * 100}.00', '0.10', 'towar')],
                        opiekun=f'Opiekun {i}')
        # Handlowiec z jednym, ale najdrozszym zamowieniem — wpada do ogona.
        _zamowienie(99, date(2026, 9, 4), [('50000.00', '0.10', 'towar')],
                    opiekun='Zenon Ogon')
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('opiekun')]

    assert karta['najlepszy']['etykieta'] == 'Zenon Ogon'
    assert karta['najlepszy']['srednie'] == 50000.0


def test_roznica_ceny_wykonczenia_przychodzi_policzona_z_serwera(client, app):
    with app.app_context():
        surowe = _zamowienie(1, date(2026, 9, 3), [('1000.00', '1.00', 'towar')])
        lakierowane = _zamowienie(2, date(2026, 9, 4), [('1500.00', '1.00', 'towar')])
        db.session.commit()
        for pozycja in db.session.query(SalesOrderItem).filter_by(
                order_id=lakierowane.id).all():
            pozycja.finish_state = 'lakierowane bezbarwne'
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('wykonczenie')]

    assert karta['roznica_do_surowego'] == 50.0


def test_roznica_ceny_wykonczenia_bez_surowego_to_None(client, app):
    with app.app_context():
        zam = _zamowienie(1, date(2026, 9, 3), [('1000.00', '1.00', 'towar')])
        db.session.commit()
        for pozycja in db.session.query(SalesOrderItem).filter_by(order_id=zam.id).all():
            pozycja.finish_state = 'lakierowane bezbarwne'
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('wykonczenie')]

    assert karta['roznica_do_surowego'] is None


@pytest.mark.parametrize('dodatek', [
    # Usluga bez wykonczenia: netto bez objetosci. To byl przypadek z produkcji.
    ('500.00', '0', 'usługa', None),
    # Pozycja bez wykonczenia, ale z objetoscia: „(brak)" to nie „wykonczone".
    ('900.00', '0.50', 'towar', None),
    # Wykonczenie bez objetosci: cena za m³ takiego wiersza nie istnieje.
    ('300.00', '0', 'towar', 'olejowane'),
], ids=['usluga_bez_wykonczenia', 'brak_wykonczenia_z_objetoscia',
        'wykonczenie_bez_objetosci'])
def test_roznica_ceny_wykonczenia_liczy_tylko_wykonczenia_z_objetoscia(client, app, dodatek):
    """Weryfikacja E8 (Z1): „Cena za m³ z wykończeniem" doliczała do strony
    wykończonej KAŻDY wiersz poza „surowy" — także „(brak)", czyli na
    produkcji usługi z netto i zerową objętością. Karta pokazywała
    +2 027,4% wobec surowego zamiast +153,5% (wrzesień 2025, bez
    lakierowanego). Żaden z trzech dodatków nie może zmienić 50,0%:
    surowy 1000 zł / 1 m³ i lakierowany 1500 zł / 1 m³."""
    netto, objetosc, grupa, wykonczenie = dodatek
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('1000.00', '1.00', 'towar')])
        lakierowane = _zamowienie(2, date(2026, 9, 4), [('1500.00', '1.00', 'towar')])
        dodatkowe = _zamowienie(3, date(2026, 9, 5), [(netto, objetosc, grupa)])
        db.session.commit()
        for zam, stan in ((lakierowane, 'lakierowane bezbarwne'), (dodatkowe, wykonczenie)):
            for pozycja in db.session.query(SalesOrderItem).filter_by(order_id=zam.id):
                pozycja.finish_state = stan
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('wykonczenie')]

    assert karta['roznica_do_surowego'] == 50.0


# --- niezmiennik miedzyekranowy: nowi klienci -------------------------------
#
# Regresja 22.09.2026: dashboard („NOWI W OKRESIE", klienci.nowi_w_okresie)
# i Eksplorator (kolumna „Nowi klienci", miary.suma.nowi_klienci) liczyly te
# sama etykiete DWOMA niezaleznymi zapytaniami i dla tego samego okresu
# dawaly dwie rozne liczby (381 na dashboardzie, 380 w Eksploratorze —
# zweryfikowane na kontenerze `db`, patrz raport-fala4-klienci.md). Ten test
# pilnuje, zeby ta sama miara za ten sam okres dawala TA SAMA liczbe na obu
# ekranach, niezaleznie od tego, jak kazdy z nich jest policzony pod spodem.

def test_nowi_klienci_ta_sama_liczba_dashboard_i_eksplorator(client, app):
    """Dashboard i Eksplorator maja pokazac TA SAMA liczbe „nowych klientow"
    za ten sam okres.

    Dane: jeden PRAWDZIWY nowy klient (ma zamowienie w `sales_orders`) plus
    jeden OSIEROCONY wpis w `sales_clients` — `first_order_at` w okresie
    i `orders_count=1`, ale ZERO wierszy w `sales_orders` (odtwarza
    produkcyjnego klienta „TEST Weryfikacja", id=2622). Osierocony nie ma
    wejsc do zadnej z dwoch liczb, bo nie stoi za nim zadne realne zamowienie
    — a obie maja wyjsc te sama.
    """
    with app.app_context():
        prawdziwy = SalesClient(display_name='Nowy Klient', orders_count=1,
                                lifetime_net=Decimal('1000.00'),
                                first_order_at=date(2026, 9, 3))
        db.session.add(prawdziwy)
        db.session.flush()
        _zamowienie(1, date(2026, 9, 3), [('1000.00', '0.50', 'towar')],
                    client_id=prawdziwy.id)
        # Osierocony: first_order_at i orders_count ustawione, ale bez
        # jakiegokolwiek wiersza w sales_orders.
        db.session.add(SalesClient(display_name='TEST Weryfikacja', orders_count=1,
                                   lifetime_net=Decimal('0.00'),
                                   first_order_at=date(2026, 9, 18)))
        db.session.commit()

    dashboard = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()
    eksplorator = client.get(
        '/reports/api/eksplorator?od=2026-09-01&do=2026-09-21'
        '&wymiar=order_source&miara=netto').get_json()

    z_dashboardu = dashboard['karty'][klucz_karty('klienci')]['nowi_w_okresie']
    z_eksploratora = eksplorator['miary']['suma']['nowi_klienci']

    # Osobne asercje na wartosc: gdyby obie strony byly rowne, ale obie
    # zliczaly osieroconego (np. 2 == 2), test przeszedlby mimo bledu.
    assert z_dashboardu == 1
    assert z_eksploratora == 1
    assert z_dashboardu == z_eksploratora


# --- parametry i walidacja --------------------------------------------------

def test_brak_parametrow_daje_biezacy_miesiac(client):
    dane = client.get('/reports/api/analytics').get_json()
    assert dane['okres']['od'].endswith('-01')


def test_stary_parametr_wymiaru_w_adresie_jest_ignorowany(client):
    """Do Planu D `?kanal=payment_date` dawalo 400 — adres sterowal wymiarem
    karty. Dzis wymiar jest czescia ZAPISANEGO ukladu (walidacja w
    `POST /api/uklad`), a parametr z adresu nie ma na co wplynac: odpowiedz
    jest ta sama, co bez niego. Asercja na KLUCZE kart, nie tylko na 200 —
    inaczej test przeszedlby tez wtedy, gdyby parametr po cichu dzialal."""
    odpowiedz = client.get('/reports/api/analytics?kanal=payment_date'
                           '&opiekun=gluing_done_at&naleznosci=wood_species')
    assert odpowiedz.status_code == 200
    karty = odpowiedz.get_json()['karty']
    assert set(karty) == {i.klucz for i in UKLAD_DOMYSLNY if KATALOG[i.typ].wymiarowy}


def test_data_w_zlym_formacie_daje_400(client):
    odpowiedz = client.get('/reports/api/analytics?od=wczoraj&do=2026-09-21')
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zly_okres'


def test_od_pozniejsze_niz_do_daje_400(client):
    assert client.get('/reports/api/analytics?od=2026-09-30&do=2026-09-01').status_code == 400


def test_data_przed_dolna_granica_daje_400_a_nie_overflow(client):
    """poprzedni_okres odejmuje dlugosc okresu od `od` bez dolnej granicy —
    przy dacie bliskiej date.min leci OverflowError „date value out of range"
    i uzytkownik dostaje 500 zamiast czytelnego 400."""
    odpowiedz = client.get('/reports/api/analytics?od=0001-01-01&do=0001-12-31')
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zly_okres'


def test_krotki_okres_przy_dacie_min_tez_daje_400(client):
    """Krotki okres nie omija problemu: poprzedni_okres i tak cofa sie
    o dzien przed `od`."""
    assert client.get('/reports/api/analytics?od=0001-01-01&do=0001-01-05').status_code == 400


def test_eksplorator_tez_odrzuca_date_przed_dolna_granica(client):
    odpowiedz = client.get('/reports/api/eksplorator?od=0001-01-01&do=0001-01-05')
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zly_okres'


def test_trasa_html_przy_dacie_min_wraca_do_domyslnego_okresu(client):
    """Nieaktualna zakladka ma pokazac dashboard, a nie strone bledu — to ta
    sama umowa co przy zlym wymiarze."""
    assert client.get('/reports/analiza?od=0001-01-01&do=0001-12-31').status_code == 200


def test_zapisany_wymiar_karty_wchodzi_do_odpowiedzi(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')], opiekun='Ewa Fikcyjna')
        db.session.commit()
    _uklad(client, ('kanal', 'caretaker'))

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('kanal', 'caretaker')]

    assert karta['wymiar'] == 'caretaker'
    assert karta['wiersze'][0]['wartosc'] == 'Ewa Fikcyjna'


def test_wymiary_dostepne_pochodza_z_rejestru_pol(client):
    from modules.reports.fields import wymiary

    lista = client.get('/reports/api/analytics').get_json()['wymiary_dostepne']

    assert {w['nazwa'] for w in lista} == set(wymiary())
    assert all(w['etykieta'] for w in lista)


# --- wnioski (karta „Statystyki") -------------------------------------------

from modules.reports.analiza_service import formatuj_liczbe, wnioski  # noqa: E402


def test_formatuj_liczbe_po_polsku():
    assert formatuj_liczbe(Decimal('369226')) == '369 226'
    assert formatuj_liczbe(Decimal('51.94'), 1) == '51,9'
    assert formatuj_liczbe(Decimal('17032.5'), 2) == '17 032,50'
    assert formatuj_liczbe(None) == '—'


def _wiersze_kanalu():
    """Wiersze po `order_source` — od Planu D `wnioski` dostaje je OSOBNO,
    bo karty kanalow moze na pulpicie nie byc, a wniosek ma dzialac i tak."""
    return [{'wartosc': 'shop', 'etykieta': 'Sklep',
             'netto': Decimal('191628'), 'objetosc': Decimal('11.42'),
             'zamowienia': 262, 'udzial': Decimal('51.9'),
             'cena_za_m3': Decimal('16780')}]


def _dane_do_wnioskow():
    """Minimalny slownik o ksztalcie tego, co zwraca dane_dashboardu.

    Bez `karty`: wnioski czytaja z payloadu wylacznie `kpi` i `trend`."""
    return {
        'kpi': {
            'netto': Decimal('369226'), 'objetosc': Decimal('21.58'),
            'zamowienia': 423, 'saldo': Decimal('0'),
            'srednie_zamowienie': Decimal('873'), 'cena_za_m3': Decimal('17110'),
            'zmiana': {'netto': Decimal('-7.6'), 'objetosc': Decimal('-12.3'),
                       'zamowienia': Decimal('5.2'),
                       'srednie_zamowienie': Decimal('-12.2'),
                       'cena_za_m3': Decimal('4.9')},
        },
        'trend': {
            'etykiety': ['STY', 'LUT'],
            'biezacy': [
                {'rok': 2026, 'miesiac': 1, 'netto': Decimal('100000'),
                 'objetosc': Decimal('10'), 'zamowienia': 50},
                {'rok': 2026, 'miesiac': 2, 'netto': Decimal('369226'),
                 'objetosc': Decimal('21.58'), 'zamowienia': 423},
            ],
            'poprzedni': [],
        },
    }


def test_wnioski_zawsze_trzy_i_z_kompletem_kluczy():
    lista = wnioski(_dane_do_wnioskow(), _wiersze_kanalu(), {'shop': Decimal('34.4')})
    assert len(lista) == 3
    for w in lista:
        assert set(w) == {'tekst', 'kontekst', 'akcent'}
        assert w['tekst'] and w['kontekst']
    assert [w['akcent'] for w in lista] == ['accent', 'teal', 'neutral']


def test_wniosek_o_kanale_porownuje_z_poprzednim_okresem():
    tekst = wnioski(_dane_do_wnioskow(), _wiersze_kanalu(), {'shop': Decimal('34.4')})[0]['tekst']
    # We wniosku ma byc nazwa dla czlowieka, nie kod BaseLinkera.
    assert 'Sklep' in tekst
    assert '51,9%' in tekst
    assert '34,4%' in tekst


def test_wniosek_o_kanale_bez_danych_porownawczych_nie_klamie():
    tekst = wnioski(_dane_do_wnioskow(), _wiersze_kanalu(), {})[0]['tekst']
    assert '51,9%' in tekst
    assert 'brak danych porównawczych' in tekst


def test_wniosek_o_kanale_przy_pustym_okresie():
    assert 'Brak zamówień' in wnioski(_dane_do_wnioskow(), [], {})[0]['tekst']


def test_wniosek_o_cenie_wskazuje_najwyzszy_miesiac_roku():
    """Luty ma 369226/21,58 = 17 109 zl/m3, styczen 10 000 — luty wygrywa."""
    tekst = wnioski(_dane_do_wnioskow(), _wiersze_kanalu(), {})[1]['tekst']
    assert '17 110' in tekst
    assert 'najwyższa' in tekst


def test_wniosek_o_cenie_gdy_biezacy_miesiac_nie_jest_najwyzszy():
    dane = _dane_do_wnioskow()
    dane['trend']['biezacy'][0] = {'rok': 2026, 'miesiac': 1, 'netto': Decimal('400000'),
                                   'objetosc': Decimal('10'), 'zamowienia': 50}
    tekst = wnioski(dane, _wiersze_kanalu(), {})[1]['tekst']
    assert 'STY' in tekst
    assert '40 000' in tekst


def _dane_z_miesiacem_okresu(miesiace):
    """Payload do wniosku o cenie: `miesiace` to (etykieta, netto, objętość),
    ostatni jest miesiącem okresu. Cena w KPI liczy się TĄ SAMĄ funkcją co na
    pulpicie (`aggregates.kpi`) — zaokrąglona do grosza."""
    from modules.reports.aggregates import cena_netto_za_m3

    netto, objetosc = Decimal(miesiace[-1][1]), Decimal(miesiace[-1][2])
    dane = _dane_do_wnioskow()
    dane['kpi']['netto'], dane['kpi']['objetosc'] = netto, objetosc
    dane['kpi']['cena_za_m3'] = cena_netto_za_m3(netto, objetosc)
    dane['trend']['etykiety'] = [m[0] for m in miesiace]
    dane['trend']['biezacy'] = [
        {'rok': 2026, 'miesiac': i + 1, 'netto': Decimal(m[1]),
         'objetosc': Decimal(m[2]), 'zamowienia': 1}
        for i, m in enumerate(miesiace)]
    return dane


def test_wniosek_o_cenie_miesiac_okresu_rekordem_mimo_ceny_zaokraglonej_w_dol():
    """Weryfikacja partii E (Z2/D2): pulpit 1–23.09 bez buku, jesionu,
    mikrowczepu, B/B i A/A mówił „Cena netto za m³ w okresie to 20 133 zł,
    poniżej rekordu roku: 20 133 zł w WRZ." Wrzesień JEST rekordem — KPI
    zaokrągla 152 317,65 / 7,565581 = 20 132,9746 do 20 132,97, a rekord
    miesiąca szedł bez zaokrąglenia, więc „20 132,97 < 20 132,9746"."""
    dane = _dane_z_miesiacem_okresu([
        ('STY', '100000', '10'), ('SIE', '150000', '10'),
        ('WRZ', '152317.65', '7.565581')])
    assert dane['kpi']['cena_za_m3'] == Decimal('20132.97')   # zaokrąglone w dół

    tekst = wnioski(dane, _wiersze_kanalu(), {})[1]['tekst']

    assert tekst == 'Cena netto za m³ w okresie to 20 133 zł — najwyższa w tym roku.'


def test_wniosek_o_cenie_nie_stawia_tej_samej_liczby_po_obu_stronach():
    """Rekordem jest INNY miesiąc, droższy o 30 groszy. Po zaokrągleniu do
    złotówki obie ceny to 17 000 zł, więc „17 000 zł, poniżej rekordu roku:
    17 000 zł w SIE" czyta się jak sprzeczność. Zdanie mówi wtedy, że cena
    jest na poziomie rekordu, i nie powtarza liczby."""
    dane = _dane_z_miesiacem_okresu([
        ('STY', '100000', '10'), ('SIE', '170004.00', '10'),
        ('WRZ', '170001.00', '10')])

    tekst = wnioski(dane, _wiersze_kanalu(), {})[1]['tekst']

    assert tekst == 'Cena netto za m³ w okresie to 17 000 zł, na poziomie rekordu roku w SIE.'


def test_wniosek_o_srednim_zamowieniu_laczy_obie_zmiany():
    tekst = wnioski(_dane_do_wnioskow(), _wiersze_kanalu(), {})[2]['tekst']
    assert '12,2%' in tekst
    assert '5,2%' in tekst


def test_wniosek_o_srednim_zamowieniu_bez_porownania_ma_sens():
    """Partia E, punkt E7. Bez okresu porównawczego zdanie brzmiało
    „Średnie zamówienie bez porównania przy liczbie zamówień bez porównania
    — 1 356 zł na 3 339 zamówień". Ma mieć sens i bez porównania."""
    from modules.reports.analiza_service import _wniosek_srednie

    dane = {'kpi': {'srednie_zamowienie': Decimal('1356'), 'zamowienia': 3339,
                    'zmiana': {'srednie_zamowienie': None, 'zamowienia': None}}}
    wniosek = _wniosek_srednie(dane)
    assert wniosek['tekst'] == 'Średnie zamówienie: 1 356 zł na 3 339 zamówień.'
    assert 'bez porównania' not in wniosek['tekst']
    assert wniosek['kontekst'] == 'wybrany okres'

    # Z porównaniem — zdanie jak dotąd, obie zmiany ze znakiem.
    dane['kpi']['zmiana'] = {'srednie_zamowienie': Decimal('-10.1'),
                             'zamowienia': Decimal('34.4')}
    wniosek = _wniosek_srednie(dane)
    assert wniosek['tekst'] == ('Średnie zamówienie −10,1% przy liczbie zamówień '
                                '+34,4% — 1 356 zł na 3 339 zamówień.')
    assert wniosek['kontekst'] == 'wybrany okres wobec poprzedniego'


def test_endpoint_zwraca_trzy_wnioski(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('1000.00', '0.50', 'towar')])
        db.session.commit()

    lista = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()['wnioski']

    assert len(lista) == 3
    assert all(set(w) == {'tekst', 'kontekst', 'akcent'} for w in lista)


# --- opis okresu w payloadzie -----------------------------------------------

def test_payload_niesie_gotowy_opis_okresu(client):
    """Formatowanie po polsku zostaje na serwerze — JS ma tylko podstawic tekst."""
    okres = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['okres']
    assert okres['opis'] == '1–21 wrz 2026'
    assert okres['nazwa'] in ('bieżący miesiąc', 'pełny miesiąc', 'zakres własny',
                              'bieżący rok')


def test_payload_okres_ma_piec_kluczy(client):
    okres = client.get('/reports/api/analytics').get_json()['okres']
    assert set(okres) == {'od', 'do', 'stan_na', 'nazwa', 'opis'}


# --- wartosci wymiaru (zrodlo listy w popoverze filtra) ---------------------

def test_wartosci_wymiaru_pochodza_z_danych_okresu(client, app):
    """Lista w popoverze ma pokazywac to, co w okresie faktycznie jest —
    nie slownik wszystkich mozliwych wartosci."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')], kanal='shop')
        _zamowienie(2, date(2026, 9, 4), [('900.00', '0.90', 'towar')], kanal='allegro')
        _zamowienie(3, date(2026, 3, 4), [('500.00', '0.50', 'towar')], kanal='olx')
        db.session.commit()

    dane = client.get('/reports/api/wartosci-wymiaru?wymiar=order_source'
                      '&od=2026-09-01&do=2026-09-21').get_json()

    assert dane['wymiar'] == {'nazwa': 'order_source', 'etykieta': 'Kanał sprzedaży'}
    assert [w['wartosc'] for w in dane['wartosci']] == ['allegro', 'shop']
    assert [w['etykieta'] for w in dane['wartosci']] == ['Allegro', 'Sklep']
    assert dane['uciete'] is False


def test_wartosci_wymiaru_niosa_licznik_zamowien(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')], kanal='shop')
        _zamowienie(2, date(2026, 9, 4), [('100.00', '0.10', 'towar')], kanal='shop')
        db.session.commit()

    dane = client.get('/reports/api/wartosci-wymiaru?wymiar=order_source'
                      '&od=2026-09-01&do=2026-09-21').get_json()

    assert dane['wartosci'][0]['zamowienia'] == 2


def test_wartosci_wymiaru_niosa_klucz_grupy_bazy(client, app):
    """Popover zaznacza pole po KLUCZU GRUPY z serwera, nie po napisie: segment
    wybrany w jednym okresie jako „Kurier" ma zostac zaznaczony, gdy baza w innym
    okresie odda te grupe jako „kurier" (kontrola 24.09.2026)."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')], kanal='shop')
        db.session.commit()

    dane = client.get('/reports/api/wartosci-wymiaru?wymiar=order_source'
                      '&od=2026-09-01&do=2026-09-21').get_json()
    assert dane['wartosci'][0]['klucz'] == 'shop'

    from modules.reports.aggregates import klucz_grupy
    assert klucz_grupy('Kurier ') == klucz_grupy('kurier')

    with open(os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'filtr.js'),
              encoding='utf-8') as plik:
        filtr_js = plik.read()
    assert 'kluczeWartosci[nazwa][w.wartosc] = w.klucz' in filtr_js
    assert '.indexOf(w.wartosc)' not in filtr_js


def test_wartosc_pusta_jest_na_liscie_jako_brak(client, app):
    """Karty pokazuja wiersz „(brak)", wiec musi dac sie po nim filtrowac.
    W adresie to pusta wartosc po dwukropku."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')], kanal=None)
        db.session.commit()

    dane = client.get('/reports/api/wartosci-wymiaru?wymiar=order_source'
                      '&od=2026-09-01&do=2026-09-21').get_json()

    assert dane['wartosci'][0] == {'wartosc': '', 'etykieta': '(brak)', 'zamowienia': 1,
                                   'klucz': ''}


def test_wartosci_wymiaru_odrzucaja_wymiar_zlozony(client):
    """Krotka skladowych nie przechodzi przez format filtra w adresie."""
    odpowiedz = client.get('/reports/api/wartosci-wymiaru?wymiar=konfiguracja')
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zly_wymiar'


def test_wartosci_wymiaru_odrzucaja_nazwe_spoza_rejestru(client):
    assert client.get('/reports/api/wartosci-wymiaru?wymiar=paid_cash').status_code == 400


def test_wartosci_wymiaru_sa_ucinane_do_limitu(client, app):
    from modules.reports.analiza_service import LIMIT_WARTOSCI_FILTRA

    with app.app_context():
        for i in range(LIMIT_WARTOSCI_FILTRA + 5):
            _zamowienie(i + 1, date(2026, 9, 3), [(f'{1000 - i}.00', '0.10', 'towar')],
                        opiekun=f'Opiekun {i:03d}')
        db.session.commit()

    dane = client.get('/reports/api/wartosci-wymiaru?wymiar=caretaker'
                      '&od=2026-09-01&do=2026-09-21').get_json()

    assert len(dane['wartosci']) == LIMIT_WARTOSCI_FILTRA
    assert dane['uciete'] is True


# --- segment porownawczy ----------------------------------------------------

def test_bez_parametru_jest_jeden_chip_i_brak_porownania(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')])
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()

    assert len(dane['segmenty']) == 1
    assert dane['segmenty'][0]['nazwa'] == 'Wszystkie zamówienia'
    assert dane['porownanie'] is None


def test_segment_doklada_drugi_chip_z_opisem_po_polsku(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')], kanal='shop')
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21'
                      '&porownanie=order_source:shop').get_json()

    assert len(dane['segmenty']) == 2
    assert dane['segmenty'][1]['nazwa'] == 'Kanał sprzedaży: Sklep'
    assert dane['segmenty'][1]['filtr'] == 'order_source:shop'
    assert dane['segmenty'][0]['kolor'] != dane['segmenty'][1]['kolor']


def test_porownanie_niesie_wlasne_kpi(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')], kanal='shop')
        _zamowienie(2, date(2026, 9, 4), [('700.00', '0.70', 'towar')], kanal='allegro')
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21'
                      '&porownanie=order_source:shop').get_json()

    assert dane['kpi']['netto'] == 1000.0
    assert dane['porownanie']['kpi']['netto'] == 300.0
    assert dane['porownanie']['kpi']['zamowienia'] == 1


def test_porownanie_po_polu_pozycji_nie_powiela_salda(client, app):
    """REGRESJA 7,58x — tym razem przez segment porownawczy."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.01', 'towar')] * 34,
                    saldo='9969.32')
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21'
                      '&porownanie=wood_species:d%C4%85b').get_json()

    assert dane['porownanie']['kpi']['saldo'] == 9969.32


def test_wiersze_porownania_sa_wyrownane_do_wierszy_bazy(client, app):
    """JS podstawia drugi slupek po INDEKSIE, wiec wyrownanie robi serwer.
    Dopasowanie po etykiecie nie zdzialaloby nic z wierszem zbiorczym:
    „Pozostale (7)" bazy i „Pozostale (4)" segmentu to inne napisy."""
    with app.app_context():
        for i in range(6):
            _zamowienie(i + 1, date(2026, 9, 3), [(f'{600 - i * 50}.00', '0.10', 'towar')],
                        kanal=f'kanal{i}')
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21'
                      '&porownanie=order_source:kanal0|kanal5').get_json()

    baza = dane['karty'][klucz_karty('kanal')]['wiersze']
    segment = dane['porownanie']['karty'][klucz_karty('kanal')]
    assert len(segment) == len(baza)
    # kanal0 jest pierwszy w bazie i wchodzi do segmentu w calosci.
    assert segment[0]['netto'] == baza[0]['netto']
    # kanal5 wpadl do wiersza zbiorczego bazy, wiec jego netto ma sie znalezc
    # w ostatnim wierszu segmentu, a nie zniknac.
    assert baza[-1]['zbiorczy'] is True
    assert segment[-1]['netto'] == 350.0


def test_karty_bez_segmentu_nie_dostaja_drugiej_serii(client, app):
    """Statystyki, Klienci, Naleznosci i Lejek zostaja jednosegmentowe."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')], kanal='shop')
        db.session.commit()

    porownanie = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21'
                            '&porownanie=order_source:shop').get_json()['porownanie']

    assert set(porownanie['karty']) == {
        klucz_karty(typ) for typ in ('kanal', 'opiekun', 'mix', 'wojewodztwo',
                                     'wykonczenie', 'dostawa')}
    for klucz in ('klienci', 'naleznosci', 'lejek', 'wnioski'):
        assert klucz not in porownanie


def test_porownanie_niesie_wlasny_szereg_trendu(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')], kanal='shop')
        _zamowienie(2, date(2026, 9, 4), [('700.00', '0.70', 'towar')], kanal='allegro')
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21'
                      '&porownanie=order_source:shop').get_json()

    assert len(dane['porownanie']['trend']) == len(dane['trend']['biezacy'])
    assert dane['porownanie']['trend'][-1]['netto'] == 300.0


def test_zly_filtr_porownania_daje_400_na_api(client):
    odpowiedz = client.get('/reports/api/analytics?porownanie=paid_cash:100')
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zly_filtr'


def test_zly_filtr_porownania_nie_wywala_strony(client):
    """Nieaktualna zakladka ma pokazac dashboard bez segmentu, nie strone bledu."""
    odpowiedz = client.get('/reports/analiza?porownanie=paid_cash:100')
    assert odpowiedz.status_code == 200


# --- zegar: uzytkownik siedzi w Polsce, serwer chodzi na UTC ----------------

SERWIS_ANALIZY = os.path.join(KORZEN, 'modules', 'reports', 'analiza_service.py')
TRASY_ANALIZY = os.path.join(KORZEN, 'modules', 'reports', 'routers_analiza.py')


def test_stan_na_pokazuje_godzine_polska_a_nie_UTC(app):
    """Kontener i serwer chodza na UTC (zmierzone: 02:07 w kontenerze przy
    04:07 na hoscie), wiec `datetime.now()` bez strefy dawal uzytkownikowi
    godzine mlodsza o 1-2 h i dashboard wygladal na nieodswiezony."""
    import pytz
    from datetime import datetime as _dt

    strefa = pytz.timezone('Europe/Warsaw')
    with app.app_context():
        przed = _dt.now(strefa).strftime('%H:%M')
        dane = dane_dashboardu(date(2026, 9, 1), date(2026, 9, 21),
                               list(UKLAD_DOMYSLNY))
        po = _dt.now(strefa).strftime('%H:%M')

    assert dane['okres']['stan_na'] in (przed, po)


def test_dzis_lokalnie_to_dzien_w_polsce():
    """Miedzy polnoca a druga w nocy UTC jest jeszcze w dniu poprzednim —
    preset „biezacy miesiac" z przegladarki nie zgadzalby sie z serwerem."""
    import pytz
    from datetime import datetime as _dt

    from modules.reports.analiza_service import dzis_lokalnie

    assert dzis_lokalnie() == _dt.now(pytz.timezone('Europe/Warsaw')).date()


def test_analiza_nie_siega_po_zegar_serwera_wprost():
    """Regresja na cala zakladke: `datetime.now()` i `date.today()` bez strefy
    nie maja prawa wrocic do tych dwoch plikow."""
    for sciezka in (SERWIS_ANALIZY, TRASY_ANALIZY):
        zrodlo = open(sciezka, encoding='utf-8').read()
        assert 'datetime.now()' not in zrodlo, sciezka
        assert 'date.today()' not in zrodlo, sciezka


# --- segment porownawczy kontra rozbicie kanalu recznego -------------------
#
# Rozbicie liczy sie z filtrem {'order_source': KANAL_RECZNY}, a segment to
# drugi filtr — _polacz_filtry robi z nich KONIUNKCJE. Te dwa testy utrwalaja
# zachowanie zweryfikowane recznie, zeby nikt go po cichu nie zmienil.

def test_segment_zaweza_rozbicie_kanalu_recznego(client, app):
    with app.app_context():
        a = _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')],
                        kanal='personal', opiekun='Halina Ćwiczebna')
        b = _zamowienie(2, date(2026, 9, 4), [('900.00', '0.90', 'towar')],
                        kanal='personal', opiekun='Łukasz Próbny')
        db.session.commit()
        a.client_origin = 'Stały B2B'
        b.client_origin = 'Detal'
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21'
                      '&porownanie=caretaker:Halina%20%C4%86wiczebna').get_json()

    # Baza: oba zamowienia reczne. Segment: tylko zamowienie Haliny.
    assert [w['etykieta'] for w in dane['kanal_rozbicie']['wiersze']] \
        == ['Detal', 'Stały B2B']
    rozbicie_segmentu = dane['porownanie']['kanal_rozbicie']
    assert len(rozbicie_segmentu) == len(dane['kanal_rozbicie']['wiersze'])
    po_etykiecie = dict(zip([w['etykieta'] for w in dane['kanal_rozbicie']['wiersze']],
                            rozbicie_segmentu))
    assert po_etykiecie['Stały B2B']['netto'] == 300.0
    assert po_etykiecie['Detal']['netto'] == 0


def test_segment_kolidujacy_z_kanalem_recznym_daje_zera_a_nie_500(client, app):
    """„Kanal reczny" ORAZ „kanal sklep" to pustka — i tak ma byc, bo takie
    jest znaczenie koniunkcji. _polacz_filtry wstawia wtedy wartosc, ktorej
    nie ma zadna kolumna; ma ona przejsc przez SQL, a nie wywrocic zadania."""
    with app.app_context():
        reczne = _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')],
                             kanal='personal')
        db.session.commit()
        reczne.client_origin = 'Stały B2B'
        db.session.commit()

    odpowiedz = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21'
                           '&porownanie=order_source:shop')
    assert odpowiedz.status_code == 200
    rozbicie_segmentu = odpowiedz.get_json()['porownanie']['kanal_rozbicie']
    assert all(w['netto'] == 0 for w in rozbicie_segmentu)


def test_przeciecie_filtrow_laczy_wartosci_po_grupie_bazy_nie_po_zapisie():
    """Segment z popovera i pola wykluczen pochodza z DWOCH roznych zapytan,
    a baza potrafi oddac te sama grupe innym zapisem („Buk" / „buk").
    Kolacja bazy (utf8mb4_unicode_ci) je utozsamia, wiec przeciecie filtrow
    tez musi — inaczej segment na polu wykluczen pokazywal 0 zl i 0 zamowien
    (kontrola 24.09.2026). Test na funkcji, bo SQLite w testach porownuje
    napisy z uwzglednieniem wielkosci liter i nie odtworzy tego przez trase."""
    from modules.reports.analiza_service import _polacz_filtry

    wykluczenia = {'wood_species': ['buk', 'jesion', '']}
    assert _polacz_filtry(wykluczenia, {'wood_species': ['Buk']}) \
        == {'wood_species': ['buk']}
    # Diakrytyki rozkladalne i spacja na koncu tez sa ta sama grupa.
    assert _polacz_filtry({'finish_state': ['lakierowany']},
                          {'finish_state': ['Lakierowany ']}) \
        == {'finish_state': ['lakierowany']}
    # Rozne grupy dalej daja pustke, a nie cudza wartosc.
    assert _polacz_filtry(wykluczenia, {'wood_species': ['Dąb']}) \
        == {'wood_species': ['\\x00brak-takiej-wartosci']}


# --- lejek wycen ------------------------------------------------------------
# Karta odpowiada na pytanie uzytkownika: ile wycen, ile zamowionych, ile
# oplaconych, ile przeszlo do realizacji. Wszystkie piec stopni liczy sie
# z jednego zbioru — wycen UTWORZONYCH w okresie.


def _wycena(numer, kiedy, bl_order=None, akceptacja=None, kwota=None,
            zrodlo=None):
    db.session.add(Quote(quote_number=numer, created_at=kiedy,
                         base_linker_order_id=bl_order,
                         acceptance_date=akceptacja, source=zrodlo,
                         total_price=None if kwota is None else Decimal(kwota)))


def test_lejek_niesie_piec_stopni_i_statystyki_wycen(client, app):
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), bl_order='101',
                akceptacja=datetime(2026, 9, 2, 12, 0), kwota='3000.00')
        _zamowienie(101, date(2026, 9, 2), [('100.00', '0.10', 'towar')])
        db.session.add(ProductionOrder(baselinker_order_id=101,
                                       internal_order_number='W/1'))
        _wycena('2/26/W', datetime(2026, 9, 3, 10, 0), kwota='1000.00')
        db.session.commit()

    lejek = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()['lejek']

    assert [s['klucz'] for s in lejek['stopnie']] == [
        'utworzone', 'zaakceptowane', 'zamowione', 'oplacone', 'w_realizacji']
    assert [s['liczba'] for s in lejek['stopnie']] == [2, 1, 1, 1, 1]
    assert lejek['stopnie'][0]['udzial'] == 100.0
    assert lejek['stopnie'][1]['udzial'] == 50.0
    assert lejek['srednia_wycena'] == 2000.0
    assert lejek['srednia_zamowiona'] == 3000.0
    assert lejek['mediana_dni'] == 0.0
    assert lejek['mediana_probka'] == 1
    # Kazdy stopien ma etykiete Z SERWERA — przegladarka nie wymysla nazw.
    assert lejek['stopnie'][4]['etykieta'] == 'W realizacji'


def test_lejek_niesie_gotowe_podzialy_a_selektor_tylko_je_przelacza(client, app):
    """Serwer liczy KAZDY wariant podzialu naraz (0,14 s na calej bazie), wiec
    przelaczenie selektora nie kosztuje zadania ani parametru w adresie."""
    from modules.reports.analytics import WYMIARY_LEJKA
    from modules.reports.analiza_service import BEZ_PODZIALU

    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), bl_order='101', zrodlo='OLX')
        _wycena('2/26/W', datetime(2026, 9, 3, 10, 0), zrodlo='OLX')
        db.session.commit()

    lejek = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()['lejek']

    assert set(lejek['podzial']) == set(WYMIARY_LEJKA)
    # „Brak podzialu" nie jest wymiarem i nie ma wlasnych wierszy.
    assert BEZ_PODZIALU not in lejek['podzial']
    assert lejek['domyslny_wymiar'] == BEZ_PODZIALU

    # Ten sam ksztalt, co karty ze slupkami: `wiersze` to co widac od razu,
    # `ogon` to rozpisana reszta wiersza „Pozostale (N)" — tu pusta, bo dwie
    # wyceny mieszcza sie w limicie karty.
    kanaly = lejek['podzial']['order_source']
    assert [(w['etykieta'], w['wycen'], w['zamowione'], w['konwersja'])
            for w in kanaly['wiersze']] == [('OLX', 2, 1, 50.0)]
    assert kanaly['ogon'] == []


def test_wymiary_lejka_maja_nazwy_z_rejestru_ale_wlasne_etykiety(client, app):
    """NAZWA idzie z rejestru pol, ETYKIETA jest wlasna — i tak ma zostac.

    Lejek grupuje po kolumnach WYCENY (`quotes.user_id`, `quotes.source`),
    a rejestr podpisuje kolumny ZAMOWIENIA (`sales_orders.caretaker`,
    `sales_orders.order_source`). Zbiory wartosci sa niemal rozlaczne, wiec
    wspolny podpis pozwolilby zestawic ze soba liczby bez wspolnego
    mianownika — pelne uzasadnienie w tescie
    `test_etykiety_lejka_nie_powielaja_etykiet_z_rejestru_pol`.
    """
    from modules.reports.fields import POLA, wymiary_proste
    from modules.reports.analiza_service import BEZ_PODZIALU

    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0))
        db.session.commit()

    wymiary = client.get(
        '/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()['lejek']['wymiary']

    assert wymiary[0]['nazwa'] == BEZ_PODZIALU
    for pozycja in wymiary[1:]:
        assert pozycja['nazwa'] in wymiary_proste()
        assert pozycja['etykieta'] != POLA[pozycja['nazwa']].etykieta
    assert [p['etykieta'] for p in wymiary[1:]] == ['Autor wyceny', 'Źródło wyceny']


def test_lejek_mowi_wprost_ile_numerow_nie_ma_odpowiednika_w_sprzedazy(client, app):
    """Roznica miedzy „ma numer BaseLinkera" a „da sie dowiazac do sprzedazy"
    jest prawdziwa (na calej bazie 1365 wobec 1173). Bez tego zdania stopien
    „Oplacone" wyglada na spadek konwersji, a jest brakiem danych."""
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), bl_order='101')
        _wycena('2/26/W', datetime(2026, 9, 3, 10, 0), bl_order='999')
        _zamowienie(101, date(2026, 9, 2), [('100.00', '0.10', 'towar')])
        db.session.commit()

    lejek = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()['lejek']

    assert lejek['dopasowanych'] == 1
    assert 'do dziś' in lejek['uwaga']
    assert '2 wycen' in lejek['uwaga'] and '1;' in lejek['uwaga']


def test_lejek_bez_zadnej_wyceny_nie_dzieli_przez_zero(client, app):
    lejek = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()['lejek']

    assert [s['liczba'] for s in lejek['stopnie']] == [0, 0, 0, 0, 0]
    assert all(s['udzial'] == 0 for s in lejek['stopnie'])
    assert lejek['mediana_dni'] is None


# --- jednostki w payloadzie -------------------------------------------------
# Przegladarka NICZEGO nie zgaduje: napis „zl" przy kwocie kosztu kuriera
# i „%" na osi lejka biora sie z tego klucza, a nie z listy wpisanej
# w analiza.js. Inaczej naglowek wypisany przez szablon i tekst zlozony
# w JavaScripcie bylyby dwoma zrodlami prawdy o tej samej jednostce.

def test_payload_niesie_jednostki_wszystkich_miar_kpi(client, app):
    from modules.reports.analiza_service import JEDNOSTKI_MIAR

    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('1000.00', '0.50', 'towar')])
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()

    assert dane['jednostki'] == JEDNOSTKI_MIAR
    for klucz in dane['kpi']:
        if klucz == 'zmiana':      # zmiana jest w procentach i ma wlasny format
            continue
        assert dane['jednostki'].get(klucz), f'KPI {klucz} bez jednostki'


def test_jednostki_sa_napisami_po_polsku(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('1000.00', '0.50', 'towar')])
        db.session.commit()

    jednostki = client.get(
        '/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()['jednostki']

    assert jednostki['netto'] == 'zł'
    assert jednostki['objetosc'] == 'm³'
    assert jednostki['cena_za_m3'] == 'zł/m³'
    assert jednostki['zamowienia'] == 'szt.'
    assert jednostki['udzial'] == '%'
    # Dwie jednostki karty lejka. „dni" nie ma odpowiednika w rejestrze POL
    # (tamten opisuje kolumny bazy), wiec mieszka w JEDNOSTKI_MIAR — ale i tak
    # przychodzi z SERWERA, nie z listy wpisanej w analiza.js.
    assert jednostki['wartosc_wyceny'] == 'zł'
    assert jednostki['czas_do_zamowienia'] == 'dni'


# --- porzadek wartosci wymiaru (zgloszenie: „daty w losowej kolejnosci") -----

def test_daty_w_liscie_wartosci_ida_chronologicznie_od_najnowszej(client, app):
    """Zgloszenie uzytkownika 23.09.2026: „jak kliknę »Porównanie« i mam datę,
    to daty są w losowej kolejności".

    Kolejnosc nie byla losowa — byla malejaca po SPRZEDAZY, odziedziczona po
    `wg_wymiaru`. Dla kanalu czy opiekuna to trafne (na gorze to, co uzytkownik
    najpewniej wybierze), dla daty bez sensu. Daty maja isc po sobie, najnowsze
    na gorze, bo porownanie robi sie najczesciej do czegos swiezego.
    """
    with app.app_context():
        # Netto celowo ROSNIE wraz z data, wiec porzadek po sprzedazy dalby
        # dokladnie odwrotna kolejnosc niz chronologiczny.
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')])
        _zamowienie(2, date(2026, 9, 10), [('500.00', '0.50', 'towar')])
        _zamowienie(3, date(2026, 9, 17), [('900.00', '0.90', 'towar')])
        db.session.commit()

    dane = client.get('/reports/api/wartosci-wymiaru?wymiar=date_created'
                      '&od=2026-09-01&do=2026-09-21').get_json()

    assert [w['wartosc'] for w in dane['wartosci']] == [
        '2026-09-17', '2026-09-10', '2026-09-03']


def test_grubosci_w_liscie_wartosci_ida_rosnaco(client, app):
    """Grubosc to liczba i tez ma porzadek wlasny — od najcienszej deski.
    Ulozona po sprzedazy dawala liste nie do przejrzenia, kiedy szuka sie
    konkretnego wymiaru surowca."""
    with app.app_context():
        zam = _zamowienie(1, date(2026, 9, 3), [])
        for netto, grubosc in (('900.00', '4.00'), ('100.00', '2.00'), ('500.00', '3.00')):
            db.session.add(SalesOrderItem(
                order_id=zam.id, value_net=Decimal(netto), total_volume=Decimal('0.10'),
                group_type='towar', thickness_cm=Decimal(grubosc), quantity=1))
        db.session.commit()

    dane = client.get('/reports/api/wartosci-wymiaru?wymiar=thickness_cm'
                      '&od=2026-09-01&do=2026-09-21').get_json()

    assert [float(w['wartosc']) for w in dane['wartosci']] == [2.0, 3.0, 4.0]


def test_wymiar_bez_porzadku_wlasnego_nadal_idzie_po_sprzedazy(client, app):
    """Regresja w druga strone: poprawka dotyczy WYLACZNIE wymiarow, ktore maja
    porzadek wlasny. Kanal i opiekun maja zostac ulozone malejaco po netto."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')], kanal='allegro')
        _zamowienie(2, date(2026, 9, 4), [('900.00', '0.90', 'towar')], kanal='shop')
        db.session.commit()

    dane = client.get('/reports/api/wartosci-wymiaru?wymiar=order_source'
                      '&od=2026-09-01&do=2026-09-21').get_json()

    assert [w['wartosc'] for w in dane['wartosci']] == ['shop', 'allegro']


def test_wartosc_pusta_konczy_liste_przy_porzadku_wlasnym(client, app):
    """„(brak)" nie ma miejsca ani na osi czasu, ani na skali grubosci —
    na gorze listy zajmowaloby miejsce wartosci, ktorej uzytkownik szuka."""
    with app.app_context():
        zam = _zamowienie(1, date(2026, 9, 3), [])
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal('900.00'), total_volume=Decimal('0.10'),
            group_type='towar', thickness_cm=None, quantity=1))
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal('100.00'), total_volume=Decimal('0.10'),
            group_type='towar', thickness_cm=Decimal('2.00'), quantity=1))
        db.session.commit()

    dane = client.get('/reports/api/wartosci-wymiaru?wymiar=thickness_cm'
                      '&od=2026-09-01&do=2026-09-21').get_json()

    assert dane['wartosci'][-1]['etykieta'] == '(brak)'
    assert dane['wartosci'][-1]['wartosc'] == ''


def test_komunikat_o_ucieciu_mowi_czego_brakuje(client, app):
    """`LIMIT_WARTOSCI_FILTRA` ucina liste, ale przy porzadku po sprzedazy
    wypada z niej co innego niz przy chronologicznym. Jeden napis („Pokazano
    najwazniejsze wartosci") po wprowadzeniu porzadku wlasnego zaczal klamac:
    obciete zostaly NAJSTARSZE daty, a nie najmniej wazne."""
    from datetime import timedelta

    from modules.reports.analiza_service import LIMIT_WARTOSCI_FILTRA

    with app.app_context():
        for i in range(LIMIT_WARTOSCI_FILTRA + 5):
            _zamowienie(i + 1, date(2026, 1, 1) + timedelta(days=i),
                        [('{}.00'.format(1000 - i), '0.10', 'towar')],
                        opiekun='Opiekun {:03d}'.format(i))
        db.session.commit()

    daty = client.get('/reports/api/wartosci-wymiaru?wymiar=date_created'
                      '&od=2026-01-01&do=2026-12-31').get_json()
    opiekunowie = client.get('/reports/api/wartosci-wymiaru?wymiar=caretaker'
                             '&od=2026-01-01&do=2026-12-31').get_json()

    assert daty['uciete'] is True and opiekunowie['uciete'] is True
    # Napis jest INNY dla kazdego porzadku i mowi, ile wartosci zostalo poza lista.
    assert 'najnowszych' in daty['opis_uciecia']
    assert 'starszych' in daty['opis_uciecia']
    assert '5' in daty['opis_uciecia']
    assert 'sprzedaży' in opiekunowie['opis_uciecia']
    assert 'najnowsz' not in opiekunowie['opis_uciecia']


def test_pelna_lista_nie_niesie_zadnego_komunikatu(client, app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')])
        db.session.commit()

    dane = client.get('/reports/api/wartosci-wymiaru?wymiar=order_source'
                      '&od=2026-09-01&do=2026-09-21').get_json()

    assert dane['uciete'] is False
    assert dane['opis_uciecia'] == ''


# --- rozwijany ogon wiersza „Pozostale (N)" ---------------------------------

def test_karta_niesie_rozpisany_ogon_obok_wiersza_zbiorczego(client, app):
    """Zgloszenie uzytkownika: „Jak piszesz opcje »Pozostałe« to zróbmy ją
    klikalną, która rozwinie resztę danych".

    Ogon musi przyjsc GOTOWY w tym samym zadaniu — rozwiniecie to wylacznie
    pokazanie wierszy, ktore przegladarka juz ma. Zadna liczba nie powstaje
    w przegladarce (spec 6.1)."""
    with app.app_context():
        for i in range(9):
            _zamowienie(i + 1, date(2026, 9, 3),
                        [('{}.00'.format(900 - i * 100), '0.10', 'towar')],
                        opiekun='Opiekun {}'.format(i))
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('opiekun')]

    assert karta['wiersze'][-1]['etykieta'] == 'Pozostałe (5)'
    assert len(karta['ogon']) == 5
    # Wiersze ogona to PRAWDZIWE wartosci wymiaru, nie kolejne podsumowania.
    assert [w['zbiorczy'] for w in karta['ogon']] == [False] * 5
    assert [w['etykieta'] for w in karta['ogon']] == [
        'Opiekun 4', 'Opiekun 5', 'Opiekun 6', 'Opiekun 7', 'Opiekun 8']


def test_suma_ogona_zgadza_sie_z_wierszem_zbiorczym(client, app):
    """Rozwiniecie nie ma prawa zmienic liczby w wierszu „Pozostale" —
    to ta sama wielkosc, raz zwinieta, raz rozpisana."""
    with app.app_context():
        for i in range(9):
            _zamowienie(i + 1, date(2026, 9, 3),
                        [('{}.55'.format(900 - i * 100), '0.10', 'towar')],
                        opiekun='Opiekun {}'.format(i))
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('opiekun')]

    zbiorczy = karta['wiersze'][-1]
    assert zbiorczy['zbiorczy'] is True
    assert round(sum(w['netto'] for w in karta['ogon']), 2) == round(zbiorczy['netto'], 2)
    assert sum(w['zamowienia'] for w in karta['ogon']) == zbiorczy['zamowienia']


def test_karta_bez_ogona_ma_pusta_liste_a_nie_brak_klucza(client, app):
    """Front ma JEDEN kontrakt: `ogon` istnieje zawsze, tylko bywa pusty."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')], kanal='shop')
        db.session.commit()

    karty = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty']

    # Kazda karta w payloadzie — takze obie kubelkowe, ktore od Planu D
    # mieszkaja w `karty` razem z reszta.
    assert karty
    for klucz, karta in karty.items():
        assert karta['ogon'] == [], klucz


def test_kazda_karta_ktora_lumpuje_ogon_go_rozpisuje(client, app):
    """Poprawka dotyczy KAZDEJ karty z wierszem zbiorczym, nie tylko jednej."""
    with app.app_context():
        for i in range(12):
            _zamowienie(i + 1, date(2026, 9, 3),
                        [('{}.00'.format(900 - i * 10), '0.10', 'towar')],
                        kanal='kanal{}'.format(i), opiekun='Opiekun {}'.format(i))
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()

    for klucz in ('kanal', 'opiekun'):
        karta = dane['karty'][klucz_karty(klucz)]
        zbiorczy = [w for w in karta['wiersze'] if w['zbiorczy']]
        assert zbiorczy, 'karta {} bez wiersza zbiorczego'.format(klucz)
        ile_w_etykiecie = int(zbiorczy[0]['etykieta'].split('(')[1].rstrip(')'))
        assert len(karta['ogon']) == ile_w_etykiecie


def test_ogon_dostaje_wlasna_serie_porownawcza(client, app):
    """Bez niej rozwiniety wiersz pokazywalby przy wlaczonym segmencie sam
    slupek bazowy, a wiersze nad nim — dwa: ten sam wiersz wygladalby inaczej
    przed rozwinieciem i po nim."""
    with app.app_context():
        for i in range(6):
            _zamowienie(i + 1, date(2026, 9, 3),
                        [('{}.00'.format(600 - i * 50), '0.10', 'towar')],
                        kanal='kanal{}'.format(i))
        db.session.commit()

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21'
                      '&porownanie=order_source:kanal5').get_json()

    karta = dane['karty'][klucz_karty('kanal')]
    ogony = dane['porownanie']['ogony'][klucz_karty('kanal')]
    assert len(ogony) == len(karta['ogon'])
    # kanal5 wpadl do ogona i w segmencie ma swoje pelne netto.
    indeks = [w['wartosc'] for w in karta['ogon']].index('kanal5')
    assert ogony[indeks]['netto'] == 350.0


def test_podzial_lejka_tez_rozpisuje_ogon(client, app):
    """Ta sama umowa co na kartach ze slupkami: `wiersze` plus `ogon`."""
    with app.app_context():
        for i in range(8):
            _wycena('{}/26/W'.format(i + 1), datetime(2026, 9, 2, 10, 0),
                    zrodlo='Kanal {}'.format(i))
        db.session.commit()

    podzial = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                    .get_json()['lejek']['podzial']['order_source']

    assert podzial['wiersze'][-1]['etykieta'] == 'Pozostałe (4)'
    assert len(podzial['ogon']) == 4
    assert sum(w['wycen'] for w in podzial['ogon']) == podzial['wiersze'][-1]['wycen']


# --- karty kubelkowe: „Klienci wedlug" i „Naleznosci wedlug" ----------------

def test_karty_kubelkowe_maja_wiecej_niz_jeden_wymiar(client, app):
    """Zgloszenie uzytkownika: „dropdown na »Klienci według« nie rozwija się".
    Selektor byl `disabled`, bo mial jedna opcje. Teraz ma prawdziwe wymiary
    — nazwy z rejestru pol, nie z listy wpisanej na sztywno w HTML."""
    from modules.reports.analiza_service import (
        LICZBA_ZAMOWIEN, WIEK_ZAMOWIENIA, WYMIARY_KLIENTOW, WYMIARY_NALEZNOSCI,
    )
    from modules.reports.fields import POLA

    _uklad(client, ('klienci', 'liczba_zamowien'), NALEZNOSCI)
    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()

    klienci = dane['karty'][klucz_karty('klienci')]['wymiary']
    naleznosci = dane['karty'][klucz_karty('naleznosci')]['wymiary']
    assert klienci[0] == {'nazwa': LICZBA_ZAMOWIEN, 'etykieta': 'Liczba zamówień'}
    assert naleznosci[0] == {'nazwa': WIEK_ZAMOWIENIA, 'etykieta': 'Wiek zamówienia'}
    assert len(klienci) == 1 + len(WYMIARY_KLIENTOW)
    assert len(naleznosci) == 1 + len(WYMIARY_NALEZNOSCI)
    # ETYKIETY ida z rejestru — „Opiekun" znaczy tu to samo, co na kazdej innej
    # karcie. Zadnego wlasnego slownika nazw.
    for pozycja in klienci[1:] + naleznosci[1:]:
        assert pozycja['etykieta'] == POLA[pozycja['nazwa']].etykieta
    assert dane['karty'][klucz_karty('klienci')]['wymiar'] == LICZBA_ZAMOWIEN
    assert dane['karty'][klucz_karty('naleznosci')]['wymiar'] == WIEK_ZAMOWIENIA


def test_klienci_wedlug_wymiaru_to_kolo_netto_okresu(client, app):
    """Partia E, punkt E2 — cytat prezesa: „kafel »Klienci wg.« ma mieć wykres
    kołowy, pod nim informacje % oraz kwotowe". Kawałek koła to WARTOŚĆ
    w złotych: każde zamówienie należy do jednego kawałka, więc % sumuje się
    do 100, a złotówki do netto okresu. Przy liczbie klientów ten sam klient
    trafiałby do kilku kawałków.

    Netto liczy się tak samo jak w „Sprzedaż netto według": z POZYCJI, za
    wybrany okres."""
    with app.app_context():
        for i in range(3):
            db.session.add(SalesClient(email_norm='k{}@x.pl'.format(i),
                                       orders_count=1, lifetime_net=Decimal('100')))
        db.session.flush()
        klienci = SalesClient.query.order_by(SalesClient.id).all()
        _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')],
                    opiekun='Anna', client_id=klienci[0].id)
        _zamowienie(2, date(2026, 9, 4), [('300.00', '0.30', 'towar')],
                    opiekun='Anna', client_id=klienci[0].id)   # ten sam klient
        _zamowienie(3, date(2026, 9, 5), [('300.00', '0.30', 'towar')],
                    opiekun='Anna', client_id=klienci[1].id)
        _zamowienie(4, date(2026, 9, 6), [('600.00', '0.60', 'towar')],
                    opiekun='Bartosz', client_id=klienci[2].id)
        db.session.commit()
    _uklad(client, ('klienci', 'caretaker'))

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()
    karta = dane['karty'][klucz_karty('klienci', 'caretaker')]

    # Nagłówek kolumny kwoty to „Netto", jak na każdej karcie netto.
    assert karta['naglowek'] == {'podpis': 'Netto', 'jednostka': 'zł', 'miara': 'netto'}
    assert [(w['etykieta'], w['netto'], w['udzial']) for w in karta['wiersze']] == [
        ('Anna', 900.0, 60.0), ('Bartosz', 600.0, 40.0)]
    # Środek pierścienia: największy kawałek — policzony na serwerze.
    assert karta['najwiekszy'] == {'etykieta': 'Anna', 'udzial': 60.0}


def test_karta_klientow_na_kubelkach_zostaje_przy_wartosci_zamowien(client, app):
    """Kubełki zostają przy `lifetime_net` z całej historii — tak było i tak
    zostaje (partia E, punkt E2). Zmienia się tylko to, że kawałki niosą
    udział % policzony na serwerze."""
    with app.app_context():
        db.session.add(SalesClient(email_norm='k1@x.pl',
                                   orders_count=1, lifetime_net=Decimal('2500')))
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('klienci')]

    assert karta['naglowek'] == {'podpis': 'Netto', 'jednostka': 'zł', 'miara': 'netto'}
    assert [(w['etykieta'], w['netto'], w['udzial']) for w in karta['wiersze']] == [
        ('1 zam.', 2500.0, 100.0), ('2–3', 0, 0), ('4–9', 0, 0), ('10+', 0, 0)]
    assert karta['najwiekszy'] == {'etykieta': '1 zam.', 'udzial': 100.0}


def test_srodek_kola_to_najwiekszy_kawalek_a_nie_pierwszy_wiersz(client, app):
    """Kubełki mają stałą kolejność („1 zam.", „2–3", „4–9", „10+"), więc
    pierwszy wiersz nie musi być największy. Środek pierścienia wskazuje
    serwer — największy kawałek. Weryfikacja partii E (M13): podmiana na
    „pierwszy wiersz" przechodziła przez testy, bo w każdym największy był
    akurat pierwszy."""
    with app.app_context():
        db.session.add(SalesClient(email_norm='k1@x.pl',
                                   orders_count=1, lifetime_net=Decimal('1000')))
        db.session.add(SalesClient(email_norm='k2@x.pl',
                                   orders_count=12, lifetime_net=Decimal('3000')))
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('klienci')]

    assert [(w['etykieta'], w['udzial']) for w in karta['wiersze']] == [
        ('1 zam.', 25.0), ('2–3', 0), ('4–9', 0), ('10+', 75.0)]
    assert karta['najwiekszy'] == {'etykieta': '10+', 'udzial': 75.0}


def test_srodek_kola_pomija_wiersz_pozostale():
    """Weryfikacja partii E (Z5): wymiar Województwo, wrzesień — środek koła
    klientów mówił „57,4% Pozostałe (14)", a karta wykończeń pokazuje
    w środku zawsze NAZWANY wiersz. Jedna reguła w obu kołach: największy
    kawałek, który nie jest wierszem zbiorczym."""
    from modules.reports.analiza_service import _srodek_kola, _wiersze_kola

    pary = [(n, n, Decimal(v)) for n, v in
            (('A', 30), ('B', 20), ('C', 15), ('D', 14), ('E', 13), ('F', 12))]
    wiersze, _, najwiekszy = _wiersze_kola(pary, 4)
    # „Pozostałe (3)" = 39 zł, więcej niż największy nazwany kawałek (30 zł).
    assert wiersze[-1]['zbiorczy'] and wiersze[-1]['netto'] > wiersze[0]['netto']
    assert najwiekszy == {'etykieta': 'A', 'udzial': wiersze[0]['udzial']}
    assert _srodek_kola(wiersze) == najwiekszy
    # Same kawałki zerowe albo sam wiersz zbiorczy — środka nie ma.
    assert _srodek_kola([{'etykieta': 'X', 'netto': Decimal('0'), 'udzial': Decimal('0'),
                          'zbiorczy': False}]) is None


def test_karta_wykonczen_niesie_srodek_z_tej_samej_reguly(client, app):
    """Środek pierścienia wykończeń liczy SERWER tą samą funkcją co koło
    klientów — przeglądarka nie wybiera go już sama (`wiersze[0]`)."""
    with app.app_context():
        for bl_id, wykonczenie, netto in ((1, 'surowy', '1000.00'),
                                          (2, 'lakierowany', '600.00'),
                                          (3, 'olejowany', '550.00'),
                                          (4, 'bejcowany', '500.00')):
            zam = _zamowienie(bl_id, date(2026, 9, 3), [(netto, '0.10', 'towar')])
            db.session.flush()
            db.session.query(SalesOrderItem).filter_by(order_id=zam.id) \
                .update({'finish_state': wykonczenie})
        db.session.commit()

    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('wykonczenie')]
    # Limit karty to 3 wiersze: surowy, lakierowany i „Pozostałe (2)" = 1050 zł,
    # czyli więcej niż surowy — środek i tak pokazuje surowy.
    assert karta['wiersze'][-1]['zbiorczy']
    assert karta['wiersze'][-1]['netto'] > karta['wiersze'][0]['netto']
    assert karta['najwiekszy'] == {'etykieta': 'surowy',
                                   'udzial': karta['wiersze'][0]['udzial']}


def test_js_oba_kola_biora_srodek_z_payloadu_jedna_funkcja():
    """Jedna reguła wyboru środka — po stronie serwera. JS nie wybiera
    `wiersze[0]` ani niczego innego; obie karty rysują środek tą samą funkcją."""
    import re
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'modules', 'reports', 'static', 'js', 'analiza.js'),
              encoding='utf-8') as plik:
        js = plik.read()
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    js = re.sub(r'(?m)^\s*//.*$', '', js)

    def cialo(nazwa):
        return js.split('function ' + nazwa + '(')[1].split('\n  }\n')[0]

    for funkcja in ('rysujDodatkiWykonczenia', 'rysujKoloKlientow'):
        assert 'rysujSrodekPierscienia(kafelek, karta.najwiekszy)' in cialo(funkcja), funkcja
    assert 'wiersze[0]' not in cialo('rysujDodatkiWykonczenia')


def test_udzialy_kola_sumuja_sie_do_stu_metoda_najwiekszej_reszty():
    """Trzy równe kawałki zaokrąglone osobno dają 33,3 × 3 = 99,9. Wyświetlone
    procenty mają się sumować do 100,0 — nadwyżkę dostaje kawałek z największą
    resztą, a przy remisie pierwszy."""
    from modules.reports.analiza_service import _udzialy_do_stu

    assert _udzialy_do_stu([Decimal('1'), Decimal('1'), Decimal('1')]) == \
        [Decimal('33.4'), Decimal('33.3'), Decimal('33.3')]
    assert _udzialy_do_stu([Decimal('2'), Decimal('1')]) == [Decimal('66.7'), Decimal('33.3')]
    assert _udzialy_do_stu([Decimal('0'), Decimal('0')]) == [Decimal('0'), Decimal('0')]
    assert _udzialy_do_stu([]) == []
    # Ogon rozkłada się do udziału wiersza „Pozostałe", nie do stu.
    assert sum(_udzialy_do_stu([Decimal('1')] * 7, cel=Decimal('12.5'))) == Decimal('12.5')


def test_kolo_klientow_sumuje_sie_do_netto_okresu_a_procenty_do_stu(client, app):
    """Wymiar z długim ogonem: kawałki (z wierszem „Pozostałe (N)") sumują się
    do netto okresu co do grosza, procenty do 100,0, a rozpisany ogon — do
    wiersza zbiorczego, w złotych i w procentach."""
    with app.app_context():
        for i in range(7):
            _zamowienie(i + 1, date(2026, 9, 3 + i), [('{}.00'.format(100 + i * 7), '0.1', 'towar')],
                        opiekun='Opiekun {}'.format(i))
        db.session.commit()
    _uklad(client, ('klienci', 'caretaker'), ('kpi', None))

    dane = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()
    karta = dane['karty'][klucz_karty('klienci', 'caretaker')]

    assert len(karta['wiersze']) == 4
    assert karta['wiersze'][-1]['etykieta'] == 'Pozostałe (4)'
    assert karta['wiersze'][-1]['zbiorczy'] is True
    assert round(sum(w['netto'] for w in karta['wiersze']), 2) == dane['kpi']['netto']
    assert round(sum(w['udzial'] for w in karta['wiersze']), 1) == 100.0
    assert round(sum(w['netto'] for w in karta['ogon']), 2) == karta['wiersze'][-1]['netto']
    assert round(sum(w['udzial'] for w in karta['ogon']), 1) == karta['wiersze'][-1]['udzial']


def test_naleznosci_wedlug_wymiaru_sumuja_saldo_dodatnie_z_okresu(client, app):
    """Miara zostaje ta sama (saldo), wiec podpis kolumny sie nie zmienia.
    Zmienia sie ZASIEG — kubelki wieku licza na dzis, przekroj za okres."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')],
                    saldo='500.00', opiekun='Anna')
        _zamowienie(2, date(2026, 9, 4), [('300.00', '0.30', 'towar')],
                    saldo='200.00', opiekun='Anna')
        _zamowienie(3, date(2026, 9, 5), [('300.00', '0.30', 'towar')],
                    saldo='900.00', opiekun='Bartosz')
        # Nadplata NIE jest naleznoscia — tak samo jak w kubelkach wieku.
        _zamowienie(4, date(2026, 9, 6), [('300.00', '0.30', 'towar')],
                    saldo='-50.00', opiekun='Anna')
        # Poza okresem — nie ma prawa wejsc.
        _zamowienie(5, date(2026, 3, 6), [('300.00', '0.30', 'towar')],
                    saldo='7000.00', opiekun='Anna')
        db.session.commit()

    _uklad(client, ('naleznosci', 'caretaker'))
    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('naleznosci', 'caretaker')]

    assert karta['naglowek'] == {'podpis': 'Saldo', 'jednostka': 'zł', 'miara': 'saldo'}
    assert [(w['etykieta'], w['liczba']) for w in karta['wiersze']] == [
        ('Bartosz', 900.0), ('Anna', 700.0)]


def test_naleznosci_wg_wymiaru_nie_powielaja_salda_przez_pozycje(client, app):
    """REGRESJA 7,58x — tym razem przez przekroj karty naleznosci. Saldo zyje
    na zamowieniu; join z pozycjami pomnozylby je przez ich liczbe."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.01', 'towar')] * 34,
                    saldo='9969.32', opiekun='Anna')
        db.session.commit()

    _uklad(client, ('naleznosci', 'caretaker'))
    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('naleznosci', 'caretaker')]

    assert [(w['etykieta'], w['liczba']) for w in karta['wiersze']] == [('Anna', 9969.32)]


def test_adnotacja_karty_kubelkowej_mowi_prawde_o_zasiegu(client, app):
    """Kubelki licza sie z calej historii (klienci) albo na dzis (naleznosci),
    a przekroj po wymiarze — za wybrany okres. Jedno zdanie dla obu stanow
    musialoby jednemu z nich klamac, wiec zdanie jedzie z serwera."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), [('300.00', '0.30', 'towar')], saldo='10.00')
        db.session.commit()

    _uklad(client, ('klienci', 'liczba_zamowien'), NALEZNOSCI)
    domyslne = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()
    _uklad(client, ('klienci', 'caretaker'), ('naleznosci', 'caretaker'))
    wymiarowe = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21').get_json()

    assert 'całej historii' in domyslne['karty'][klucz_karty('klienci')]['uwaga']
    assert 'na dziś' in domyslne['karty'][klucz_karty('naleznosci')]['uwaga']
    assert 'wybranym okresie' in \
        wymiarowe['karty'][klucz_karty('klienci', 'caretaker')]['uwaga']
    # Przekrój klientów to od partii E (E2) koło netto — uwaga mówi o kawałkach.
    assert 'netto' in wymiarowe['karty'][klucz_karty('klienci', 'caretaker')]['uwaga']
    assert 'wybranego okresu' in \
        wymiarowe['karty'][klucz_karty('naleznosci', 'caretaker')]['uwaga']


def test_karta_naleznosci_odrzuca_wymiar_pozycji(client):
    """Saldo zyje na ZAMOWIENIU. Grupowanie po kolumnie pozycji pomnozyloby je
    przez liczbe pozycji — to ten sam blad 7,58x, ktory zamknal `aggregates`.
    Od Planu D wymiar karty przychodzi z ZAPISANEGO ukladu, wiec bramka stoi
    na zapisie: ma odpowiedziec 400, a nie zapisac kafelka z zawyzona liczba."""
    odpowiedz = client.post('/reports/api/uklad', json={'uklad': [
        {'typ': 'naleznosci', 'wymiar': 'wood_species'}]})
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zly_uklad'


def test_karta_klientow_odrzuca_wymiar_spoza_swojej_listy(client):
    """Lista karty jest WEZSZA niz rejestr: gatunek czy grubosc opisuja deske,
    nie klienta."""
    assert client.post('/reports/api/uklad', json={'uklad': [
        {'typ': 'klienci', 'wymiar': 'thickness_cm'}]}).status_code == 400


def test_zly_wymiar_karty_kubelkowej_nie_wywala_strony_html(client):
    """Nieaktualna zakladka ma pokazac dashboard, nie strone bledu — ta sama
    zasada, co przy zlym wymiarze pozostalych kart."""
    assert client.get('/reports/analiza?klienci=thickness_cm').status_code == 200


def test_karty_kubelkowe_tez_rozpisuja_ogon(client, app):
    """Wiersz „Pozostale (N)" na tych kartach ma dzialac tak samo jak wszedzie."""
    with app.app_context():
        for i in range(9):
            _zamowienie(i + 1, date(2026, 9, 3), [('300.00', '0.30', 'towar')],
                        saldo='{}.00'.format(900 - i * 10),
                        opiekun='Opiekun {}'.format(i))
        db.session.commit()

    _uklad(client, ('naleznosci', 'caretaker'))
    karta = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21') \
                  .get_json()['karty'][klucz_karty('naleznosci', 'caretaker')]

    assert karta['wiersze'][-1]['etykieta'] == 'Pozostałe (5)'
    assert len(karta['ogon']) == 5
    assert round(sum(w['liczba'] for w in karta['ogon']), 2) == \
        round(karta['wiersze'][-1]['liczba'], 2)


# --- partia E, punkt E7 (backend) -------------------------------------------

def test_pochodzenie_bez_wymiaru_nie_wywraca_api_z_ukladem_domyslnym(client, app, monkeypatch):
    """Rozbicie kanału ręcznego grupuje po `client_origin` wpisanym w serwisie
    na sztywno. Do partii E pole, które straciło wymiar=True w `fields.py`,
    dawało 500 na KAŻDYM /api/analytics z układem domyślnym. Teraz blok jest
    None, a pulpit się liczy. Rejestr podmieniamy, pliku nie ruszamy."""
    import dataclasses
    from modules.reports.fields import POLA

    monkeypatch.setitem(POLA, 'client_origin',
                        dataclasses.replace(POLA['client_origin'], wymiar=False))
    odpowiedz = client.get('/reports/api/analytics?od=2026-09-01&do=2026-09-21')
    assert odpowiedz.status_code == 200
    dane = odpowiedz.get_json()
    assert dane['kanal_rozbicie'] is None
    assert dane['wnioski'] is not None
    assert klucz_karty('kanal') in dane['karty']
