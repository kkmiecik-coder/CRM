# -*- coding: utf-8 -*-
"""Monitory hali, wyswietlacz ESP i firmware po podziale Wykanczania.

Piec pulapek, ktore te testy pilnuja:

1. MONITOR_STATION_MAP to jednoczesnie ROUTING (klucz = segment URL)
   i zrodlo etykiety kafla. Brak wpisu = 404 na monitorze stanowiska.
2. monitors.py trzyma DWIE niezalezne kopie map statusow — jedna dla widoku
   HTML (:141-169), druga dla AJAX-a (:289-317). Poprawienie jednej daje
   "dobrze po wejsciu, zle po pierwszym auto-odswiezeniu", wiec kazda kopia
   ma wlasny test, idacy przez wlasny endpoint.
3. Adresy kafli w monitors_select.html sa LITERALAMI, nie url_for — grep po
   url_for ich nie znajdzie.
4. access_denied.html renderuje WYLACZNIE error_message (:98); error_details
   jest gubione. Liste dostepnych stanowisk sprawdzamy wiec podmieniajac
   render_template, a nie asercja na tresci HTML.
5. Kontrakt CRM<->firmware sprawdzamy WYLACZNIE na plikach sledzonych przez
   git. Katalog docs/superpowers/ jest w .gitignore (:241) — na czystym
   klonie repo tych dokumentow nie ma i test czytajacy je wywalilby sie
   przez FileNotFoundError.

Ten plik nie zaklada tabeli prod_product_events, bo nie robi tego zaden inny
plik w pakiecie — listener audytu milczy w calym przebiegu i tak ma zostac.

Fixture montuje station_bp pod /production, bo ip_security_middleware()
przepuszcza wylacznie sciezki z tym prefiksem (security_service.py:559),
a test_client ma remote_addr 127.0.0.1 z ALWAYS_ALLOWED_IPS (:53) — filtr IP
zwraca True zanim padnie jakiekolwiek zapytanie do bazy (:84).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Blueprint, Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionOrder, ProductionProduct,
)
from modules.production.services.station_catalog import STATION_ORDER
from modules.users.models import User
# configure_mappers() przy pierwszym zapytaniu konfiguruje CALY rejestr —
# bez tych importow wywala sie na relationship('Multiplier') / ('Client').
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLONY = os.path.join(KORZEN, 'modules', 'production', 'templates')
STATYKA = os.path.join(KORZEN, 'modules', 'production', 'static')

# LONGTEXT (MySQL) nie istnieje w SQLite — jak w pozostalych pakietach.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

TABELE = [m.__table__ for m in (
    User, ProductionConfig, ProductionOrder, ProductionProduct, ProductionConfiguration,
)]


def _plik(*czesci):
    """Tresc pliku repo — do testow na literaly w szablonach, CSS i firmware.

    Tylko pliki SLEDZONE przez git. Nic z docs/superpowers/ (gitignore:241).
    """
    with open(os.path.join(KORZEN, *czesci), encoding='utf-8') as f:
        return f.read()


@pytest.fixture()
def app():
    from modules.production.routers.stations import station_bp

    app = Flask(__name__, template_folder=SZABLONY)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['LOGIN_DISABLED'] = True

    # Nazwa blueprintu MUSI brzmiec 'production' — szablony monitorow wolaja
    # url_for('production.static', ...) i url_for('production.production_stations.*').
    produkcja = Blueprint('production', __name__, static_folder=STATYKA,
                          static_url_path='/production-static')
    produkcja.register_blueprint(station_bp, url_prefix='/stations')
    app.register_blueprint(produkcja, url_prefix='/production')
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABELE)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


_licznik = [0]


def _produkt(status, kolumna_ilosci, zrobione=3, ilosc=10):
    """Jeden produkt w jednym zamowieniu, z odbita czescia sztuk na stanowisku."""
    _licznik[0] += 1
    n = _licznik[0]
    zamowienie = ProductionOrder(baselinker_order_id=90000 + n,
                                 internal_order_number=f'26/{n:05d}',
                                 client_name='Klient Testowy')
    db.session.add(zamowienie)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=zamowienie.id, short_product_id=f'26{n:03d}_1',
        product_sequence_in_order=1, original_product_name='Blat debowy',
        quantity=ilosc, volume_m3=0.5, current_status=status)
    setattr(produkt, kolumna_ilosci, zrobione)
    db.session.add(produkt)
    db.session.commit()
    return produkt


def test_mapa_monitorow_pokrywa_caly_katalog_stanowisk():
    """Kazde stanowisko z katalogu ma swoj monitor — i w tej samej kolejnosci."""
    from modules.production.routers.stations import MONITOR_STATION_MAP
    assert tuple(MONITOR_STATION_MAP) == STATION_ORDER


def test_monitor_krawedzi_czyta_status_i_kolumne_krawedzi():
    from modules.production.routers.stations import MONITOR_STATION_MAP
    wpis = MONITOR_STATION_MAP['edges']
    assert wpis['status'] == 'czeka_na_krawedzie'
    assert wpis['quantity_col'] == 'quantity_done_edges'
    assert wpis['label'] == 'Krawędzie'
    assert wpis['css_class'] == 'status-edges'


def test_monitor_lakierni_czyta_status_i_kolumne_lakierni():
    from modules.production.routers.stations import MONITOR_STATION_MAP
    wpis = MONITOR_STATION_MAP['painting']
    assert wpis['status'] == 'czeka_na_lakiernie'
    assert wpis['quantity_col'] == 'quantity_done_painting'
    assert wpis['label'] == 'Lakiernia'
    assert wpis['css_class'] == 'status-painting'


def test_monitor_lakierni_odpowiada_pod_wlasnym_adresem(app, client):
    """Routing jest dynamiczny — sam wpis w mapie otwiera nowy adres.
    Postep renderuje sie jako '6/10 szt' (monitor_station.html:97, bez spacji)."""
    with app.app_context():
        _produkt('czeka_na_lakiernie', 'quantity_done_painting', zrobione=6)
        odp = client.get('/production/stations/monitors/painting')
        assert odp.status_code == 200
        html = odp.get_data(as_text=True)
        assert 'Monitor — Lakiernia' in html
        assert '6/10 szt' in html


def test_stary_adres_monitora_wykanczania_pokazuje_krawedzie(app, client):
    """Telewizor na hali ma wbity adres /monitors/finishing — ma dzialac dalej.
    Postep '3/10 szt' dowodzi, ze alias siega po quantity_done_edges,
    a nie po nieistniejacy atrybut (getattr z defaultem 0 dalby '0/10 szt')."""
    with app.app_context():
        _produkt('czeka_na_krawedzie', 'quantity_done_edges', zrobione=3)
        odp = client.get('/production/stations/monitors/finishing')
        assert odp.status_code == 200
        html = odp.get_data(as_text=True)
        assert 'Monitor — Krawędzie' in html
        assert '3/10 szt' in html


def test_ajax_starego_adresu_oddaje_kolejke_krawedzi(app, client):
    """Druga polowa aliasu: auto-odswiezanie telewizora. Bez tej poprawki
    ekran wstaje poprawnie i gasnie po pierwszym odswiezeniu."""
    with app.app_context():
        _produkt('czeka_na_krawedzie', 'quantity_done_edges', zrobione=3)
        odp = client.get('/production/stations/ajax/monitors/finishing')
        assert odp.status_code == 200
        dane = odp.get_json()
        assert dane['success'] is True
        assert dane['stats']['total_orders'] == 1
        assert dane['orders'][0]['status_label'] == 'Krawędzie'
        assert dane['orders'][0]['status_class'] == 'status-edges'
        assert dane['orders'][0]['completed_products'] == 3


def test_komunikat_o_nieznanym_stanowisku_wymienia_lakiernie(app, client, monkeypatch):
    """Lista dostepnych stanowisk ma sie liczyc z mapy, nie z twardego stringa.

    access_denied.html renderuje WYLACZNIE error_message (:98) — error_details
    nigdy nie trafia do HTML, wiec czytamy je podmieniajac render_template
    w przestrzeni modulu (endpoint importuje ja po nazwie, monitors.py:6).
    """
    from modules.production.routers.stations import monitors as modul_monitorow

    zapisane = {}

    def falszywy_render(nazwa_szablonu, **kwargs):
        zapisane['szablon'] = nazwa_szablonu
        zapisane.update(kwargs)
        return 'OK'

    monkeypatch.setattr(modul_monitorow, 'render_template', falszywy_render)

    with app.app_context():
        odp = client.get('/production/stations/monitors/nieistniejace')
        assert odp.status_code == 404
        assert zapisane['szablon'] == 'stations/access_denied.html'
        dostepne = zapisane['error_details']
        assert 'edges' in dostepne
        assert 'painting' in dostepne
        assert 'finishing' not in dostepne


def test_monitor_ogolny_nazywa_krawedzie_po_nowemu(app, client):
    """Pierwsza z DWOCH niezaleznych kopii map statusow w monitors.py."""
    with app.app_context():
        _produkt('czeka_na_krawedzie', 'quantity_done_edges', zrobione=4)
        odp = client.get('/production/stations/monitor')
        assert odp.status_code == 200
        html = odp.get_data(as_text=True)
        assert 'Krawędzie' in html
        assert 'status-edges' in html
        # monitor.html:138 renderuje "X / Y" ZE spacjami. Postep liczony
        # z kolumny Krawedzi; brak wpisu w status_to_station dalby "0 / 10".
        assert '4 / 10' in html


def test_monitor_ogolny_nazywa_lakiernie(app, client):
    """Lakiernia nie byla w tej mapie NIGDY — produkt na lakierni pokazywal sie
    tu z surowym statusem i postepem 0. Naprawiane przy okazji podzialu."""
    with app.app_context():
        _produkt('czeka_na_lakiernie', 'quantity_done_painting', zrobione=6)
        odp = client.get('/production/stations/monitor')
        assert odp.status_code == 200
        html = odp.get_data(as_text=True)
        assert 'Lakiernia' in html
        assert 'status-painting' in html
        assert '6 / 10' in html


def test_ajax_monitora_ogolnego_nazywa_krawedzie_po_nowemu(app, client):
    """Druga kopia map statusow — to ona zasila auto-odswiezanie monitora."""
    with app.app_context():
        _produkt('czeka_na_krawedzie', 'quantity_done_edges', zrobione=4)
        odp = client.get('/production/stations/ajax/monitor')
        assert odp.status_code == 200
        zamowienie = odp.get_json()['orders'][0]
        assert zamowienie['status_label'] == 'Krawędzie'
        assert zamowienie['status_class'] == 'status-edges'
        assert zamowienie['completed_products'] == 4


def test_ajax_monitora_ogolnego_nazywa_lakiernie(app, client):
    with app.app_context():
        _produkt('czeka_na_lakiernie', 'quantity_done_painting', zrobione=6)
        odp = client.get('/production/stations/ajax/monitor')
        assert odp.status_code == 200
        zamowienie = odp.get_json()['orders'][0]
        assert zamowienie['status_label'] == 'Lakiernia'
        assert zamowienie['status_class'] == 'status-painting'
        assert zamowienie['completed_products'] == 6


def test_ekran_wyboru_monitorow_ma_kafel_kazdego_stanowiska():
    """Adresy kafli sa LITERALAMI, nie url_for — grep po url_for ich nie znajdzie."""
    html = _plik('modules', 'production', 'templates', 'stations', 'monitors_select.html')
    for kod in STATION_ORDER:
        assert '/production/stations/monitors/' + kod + '"' in html, kod
    assert '/production/stations/monitors/finishing"' not in html
    assert 'Krawędzie' in html
    assert 'Lakiernia' in html


def test_siatka_wyboru_monitorow_miesci_siedem_kafli():
    """3x2 = szesc miejsc. Przy siedmiu kaflach ostatni wypadal poza siatke."""
    html = _plik('modules', 'production', 'templates', 'stations', 'monitors_select.html')
    assert 'grid-template-columns:repeat(4,1fr)' in html
    assert 'grid-template-rows:repeat(2,1fr)' in html
    # Wariant pionowy (max-aspect-ratio:1/1): 2 kolumny x 4 wiersze.
    assert 'grid-template-rows:repeat(4,1fr)' in html
    assert 'grid-template-rows:repeat(3,1fr)' not in html
    assert '.s.edg{--c:#1abc9c}' in html
    assert '.s.lak{--c:#e11d48}' in html
    assert '.s.fin{' not in html


def test_arkusz_monitora_v2_ma_kolory_krawedzi_i_lakierni():
    """Arkusz monitora POJEDYNCZEGO stanowiska (monitor_station.html:10)."""
    css = _plik('modules', 'production', 'static', 'css', 'stations',
                'station-monitor-v2.css')
    assert '--status-edges:' in css
    assert '--status-painting:' in css
    assert '.order-card.status-edges' in css
    assert '.order-card.status-painting' in css
    assert '.status-badge.status-edges' in css
    assert '.status-badge.status-painting' in css
    assert 'status-finishing' not in css


def test_arkusz_monitora_ogolnego_ma_kolory_krawedzi_i_lakierni():
    """DRUGI, niezalezny arkusz — monitor.html:13. Bez niego kafel Lakierni
    traci lewa krawedz koloru (border-left: 4px solid var(--border-color))."""
    css = _plik('modules', 'production', 'static', 'css', 'stations',
                'station-monitor.css')
    assert '--status-edges:' in css
    assert '--status-painting:' in css
    assert '.order-card.status-edges' in css
    assert '.order-card.status-painting' in css
    assert '.status-badge.status-edges' in css
    assert '.status-badge.status-painting' in css
    assert 'status-finishing' not in css


def test_sql_agregacji_wyswietlacza_uzywa_kolumn_krawedzi():
    """_AGGREGATION_SQL liczy sie RAZ przy imporcie modulu (:99) — nazwy kolumn
    zamrazaja sie w stringu na cale zycie procesu gunicorna."""
    from modules.production.services.display_monitor_service import _AGGREGATION_SQL
    assert 'quantity_done_edges' in _AGGREGATION_SQL
    assert 'edges_completed_at' in _AGGREGATION_SQL
    assert 'quantity_done_finishing' not in _AGGREGATION_SQL
    assert 'finishing_completed_at' not in _AGGREGATION_SQL


def test_kod_ekranu_krawedzi_pilnuje_kolejnosci_kanonicznej():
    """Pozycja 4 w STATION_CODES = ST_EDG w firmware. Przestawienie kolejnosci
    przesuwa WSZYSTKIE ekrany wyswietlacza, bez zadnego bledu."""
    from modules.production.services.display_monitor_service import STATION_CODES
    assert STATION_CODES[4] == ('edg', 'edges', 'czeka_na_krawedzie')
    assert STATION_CODES[5] == ('pnt', 'painting', 'czeka_na_lakiernie')


def test_firmware_zna_kod_ekranu_krawedzi():
    """Nieznany kod ekranu NIE daje bledu — json_parser.cpp:57 robi `continue`,
    a StationData jest zero-initowane, wiec wyswietlacz pokazuje zera.
    Awaria jest bezglosna, wiec pilnujemy zgodnosci greppem po zrodlach."""
    naglowek = _plik('tools', 'production-monitor', 'firmware', 'src', 'data_model.h')
    parser = _plik('tools', 'production-monitor', 'firmware', 'src', 'json_parser.cpp')
    assert 'ST_EDG = 4' in naglowek
    assert 'ST_FIN' not in naglowek
    # Tablica ASCII — bez polskich znakow, wyswietlacz ich nie ma.
    assert '"Krawedzie"' in naglowek
    assert '"Wykonczenie"' not in naglowek
    assert 'STATION_COUNT = 7' in naglowek
    assert '"edg"' in parser
    assert '"fin"' not in parser
    assert 'ST_FIN' not in parser


def test_firmware_i_serwis_maja_te_sama_kolejnosc_ekranow():
    """Kazdy kod ekranu z Pythona musi dac sie znalezc w parserze firmware'u."""
    from modules.production.services.display_monitor_service import STATION_CODES
    parser = _plik('tools', 'production-monitor', 'firmware', 'src', 'json_parser.cpp')
    for kod, _, _ in STATION_CODES:
        assert '"' + kod + '"' in parser, kod


def test_test_firmware_sprawdza_pozycje_krawedzi():
    """Dzis pozycja 'fin' z SAMPLE_PAYLOAD nie ma ZADNEJ asercji — sprawdzane
    sa tylko ST_CUT (:47-49) i ST_PKG (:50-52). Rename bylby niepokryty."""
    kod = _plik('tools', 'production-monitor', 'firmware', 'test',
                'test_json_parser', 'test_main.cpp')
    assert '"c":"edg"' in kod
    assert '"c":"fin"' not in kod
    assert 'p.stations[ST_EDG].ip' in kod
    assert 'p.stations[ST_EDG].d' in kod
    assert 'p.stations[ST_EDG].q' in kod
    assert 'p.stations[ST_PNT].ip' in kod


def test_kontrakt_wyswietlacza_zyje_w_sledzonych_plikach():
    """Jedyny wiazacy opis kontraktu CRM<->firmware ma byc w kodzie.

    Dotad docstring odsylal do docs/superpowers/plans/... — a ten katalog
    jest w .gitignore (:241), wiec na czystym klonie repo tego dokumentu
    NIE MA. Kontrakt bez zrodla myli przy reflashu wyswietlaczy, a test
    czytajacy taki plik wywalilby sie przez FileNotFoundError.

    Druga polowa testu to straznik symetrii: kolejnosc kodow w parserze
    firmware'u musi byc IDENTYCZNA z kolejnoscia STATION_CODES. Przesuniecie
    o jedna pozycje przesuwa wszystkie ekrany i nie daje zadnego bledu.
    """
    import re
    import modules.production.services.display_monitor_service as serwis

    doc = serwis.__doc__
    assert 'docs/superpowers' not in doc
    assert 'czeka_na_krawedzie' in doc
    assert 'czeka_na_wykanczanie' not in doc
    for kod, _, _ in serwis.STATION_CODES:
        assert kod in doc, kod

    parser = _plik('tools', 'production-monitor', 'firmware', 'src', 'json_parser.cpp')
    naglowek = _plik('tools', 'production-monitor', 'firmware', 'src', 'data_model.h')
    kody_firmware = re.findall(r'strcmp\(code,\s*"([a-z]+)"\)', parser)
    assert kody_firmware == [k for k, _, _ in serwis.STATION_CODES]
    assert 'STATION_COUNT = %d' % len(serwis.STATION_CODES) in naglowek
