# -*- coding: utf-8 -*-
"""Bramka uprawnien modulu Analizy sprzedazowej.

Dwie rzeczy: wariant rolowy (wysylka do BaseLinkera tylko admin) i as_json
na endpointach API. To drugie jest wazne z konkretnego powodu: wygasla sesja
oddajaca HTML zamiast JSON-a konczy sie w przegladarce wyjatkiem parsera
i wiecznym spinnerem, bez ani jednego komunikatu dla uzytkownika.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from decimal import Decimal

import pytest
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import reports_bp
from modules.reports.models import BaselinkerReportOrder
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.users.models import Module, User

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRASY_STAREJ = os.path.join(KORZEN, 'modules', 'reports', 'routers.py')
DEKORATOR = os.path.join(KORZEN, 'modules', 'users', 'decorators',
                         'permission_required.py')

# ODCHYLENIE OD BRIEFU: dopisano `Module` (`users_modules`). Bez tej tabeli
# `require_module_access(..., as_json=False)` na trasie HTML (`/reports/arkusz`)
# wywraca sie na `Module.query...` w galezi renderujacej `access_denied.html`
# (ta galaz nie zmienia sie w tym zadaniu — istnieje od wczesniejszego zadania
# Planu C) — zweryfikowane uruchomieniem, brief tego nie uwzglednial.
_TABLES = [m.__table__ for m in
           (User, Module, BaselinkerReportOrder, SalesClient, SalesOrder, SalesOrderItem)]

# Wszystkie endpointy API starej zakladki. Cron nie jest na liscie — ma
# wlasna bramke tokenowa, bo cron nie ma sesji.
ENDPOINTY_API_STAREJ = [
    '/api/data', '/api/sync', '/api/add-manual-row', '/api/update-manual-row',
    '/api/export-excel', '/api/dropdown-values/<field_name>', '/api/sync-statuses',
    '/api/sync-statuses-stream', '/api/delete-manual-row', '/api/fetch-orders-stream',
    '/api/fetch-orders-for-selection', '/api/save-selected-orders-with-dimensions',
    '/api/save-selected-orders', '/api/export-routimo', '/api/save-orders-with-volumes',
    '/api/map-statistics',
]


def zrodlo(sciezka):
    with open(sciezka, encoding='utf-8') as plik:
        return plik.read()


def _zbuduj(ma_dostep=True, rola='admin'):
    from modules.users.services.permission_service import PermissionService
    PermissionService.user_has_module_access = staticmethod(lambda u, m: ma_dostep)

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    app.config['SECRET_KEY'] = 'test'
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
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        db.session.add(User(email='kto@woodpower.pl', password='x',
                            role=rola, active=True))
        db.session.commit()
    return app


@pytest.fixture()
def app_admina():
    from modules.users.services.permission_service import PermissionService
    oryginal = PermissionService.user_has_module_access
    yield _zbuduj(True, 'admin')
    PermissionService.user_has_module_access = oryginal


@pytest.fixture()
def app_handlowca():
    from modules.users.services.permission_service import PermissionService
    oryginal = PermissionService.user_has_module_access
    yield _zbuduj(True, 'user')
    PermissionService.user_has_module_access = oryginal


@pytest.fixture()
def app_bez_dostepu():
    from modules.users.services.permission_service import PermissionService
    oryginal = PermissionService.user_has_module_access
    yield _zbuduj(False, 'user')
    PermissionService.user_has_module_access = oryginal


def zalogowany(app):
    klient = app.test_client()
    with klient.session_transaction() as sesja:
        sesja['user_email'] = 'kto@woodpower.pl'
    return klient


# ===== as_json na starych endpointach ==================================

def _endpointy_bez_as_json(tekst):
    """Sciezki API, ktorych PELNY blok dekoratorow (od @reports_bp.route(...)
    do `def`) nie zawiera ani bramki tokenowej crona, ani require_module_access
    z as_json=True.

    NAPRAWA ZNALEZISKA z przegladu Zadania 13: stara wersja dopasowywala
    WYLACZNIE pierwszy dekorator zaraz po route (`@(\\w+)\\(([^)]*)\\)`
    bez petli). Dekorator wstawiony MIEDZY route a require_module_access
    (np. @login_required, tak jak Zadanie 14 doklada bramke tylko-do-odczytu
    nad jedenastoma z tych samych endpointow) sprawial, ze regex lapal ten
    inny dekorator, `dekorator != 'require_module_access'` bylo prawdziwe i
    `continue` po cichu POMIJAL caly endpoint — test swiecil na zielono, nic
    nie sprawdzajac. Teraz dopasowujemy CALY blok kolejnych linii `@...` i
    szukamy w nim require_module_access(..., as_json=True) gdziekolwiek stoi.
    """
    braki = []
    for dopasowanie in re.finditer(
            r"@reports_bp\.route\(\s*['\"](/api/[^'\"]+)['\"][^)]*\)\s*"
            r"((?:@[^\n]+\n)+)\s*def", tekst):
        sciezka, blok = dopasowanie.groups()
        if 'cron_secret_required' in blok:
            continue          # cron ma wlasna bramke tokenowa
        if re.search(r"require_module_access\([^)]*\bas_json\s*=\s*True", blok):
            continue
        braki.append(sciezka)
    return braki


def test_kazdy_stary_endpoint_api_ma_as_json():
    # Zamiast dwudziestu zapytan HTTP — jedno przejscie po zrodle, po CALYM
    # bloku dekoratorow. Test zlapie takze endpoint DOPISANY pozniej bez
    # as_json, choc stalby pod dodatkowym dekoratorem.
    tekst = zrodlo(TRASY_STAREJ)
    braki = _endpointy_bez_as_json(tekst)
    assert braki == [], f'endpointy bez as_json=True: {braki}'


def test_dekorator_wstawiony_nad_uprawnieniami_nie_maskuje_braku_as_json():
    # Regresja na dokladnie ten scenariusz ze znaleziska: dekorator MIEDZY
    # route a require_module_access, ktory bez as_json=True. Stara wersja
    # (patrz opis w _endpointy_bez_as_json) dawala tu `braki == []` —
    # zmierzone na wariantach syntetycznych identycznych z tym.
    synt = (
        "@reports_bp.route('/api/test-maskowania')\n"
        "@login_required\n"
        "@require_module_access('reports')\n"
        "def widok():\n"
        "    pass\n"
    )
    assert _endpointy_bez_as_json(synt) == ['/api/test-maskowania']


def test_dekorator_wstawiony_nad_uprawnieniami_z_as_json_nie_daje_falszywego_alarmu():
    # Ten sam uklad co wyzej, ale z as_json=True — nie ma byc zgloszony.
    synt = (
        "@reports_bp.route('/api/test-ok')\n"
        "@login_required\n"
        "@require_module_access('reports', as_json=True)\n"
        "def widok():\n"
        "    pass\n"
    )
    assert _endpointy_bez_as_json(synt) == []


def test_cron_z_dodatkowym_dekoratorem_nad_soba_nadal_nie_jest_brakiem():
    synt = (
        "@reports_bp.route('/api/cron/test')\n"
        "@jakis_inny_dekorator\n"
        "@cron_secret_required\n"
        "def widok():\n"
        "    pass\n"
    )
    assert _endpointy_bez_as_json(synt) == []


def test_kazdy_prawdziwy_endpoint_api_zwraca_401_json_dla_anonima(app_admina):
    # Mocniejszy straznik niz parsowanie zrodla (zaproponowany w przegladzie):
    # zamiast czytac dekoratory z tekstu, pytamy PRAWDZIWY url_map o kazda
    # trase /reports/api/* (poza /api/cron/, ktory ma bramke tokenowa) i
    # zadamy od anonima 401 + {'error': 'unauthorized'}. To dziala niezaleznie
    # od tego, ile dekoratorow i w jakiej kolejnosci stoi nad require_module_access
    # — nie da sie tego zamaskowac kolejnoscia dekoratorow tak jak regexu.
    klient = app_admina.test_client()      # bez sesji
    sprawdzone = 0
    for regula in app_admina.url_map.iter_rules():
        if not regula.rule.startswith('/reports/api/'):
            continue
        if regula.rule.startswith('/reports/api/cron/'):
            continue
        metody = (regula.methods or set()) - {'HEAD', 'OPTIONS'}
        metoda = 'POST' if 'POST' in metody else 'GET'
        sciezka = re.sub(r'<[^>]+>', 'x', regula.rule)
        odpowiedz = klient.open(sciezka, method=metoda)
        assert odpowiedz.status_code == 401, sciezka
        assert odpowiedz.get_json() == {'error': 'unauthorized'}, sciezka
        sprawdzone += 1
    # Co najmniej szesnascie starych endpointow + nowe trasy arkusza/analizy —
    # gdyby petla trafila na pusty url_map (np. zly prefiks), test i tak
    # przeszedlby bez sprawdzenia niczego. To temu zapobiega.
    assert sprawdzone >= 16


def test_lista_endpointow_w_tescie_pokrywa_sie_ze_zrodlem():
    # Gdyby ktos dolozyl endpoint API, ta asercja wymusi dopisanie go tutaj.
    tekst = zrodlo(TRASY_STAREJ)
    ze_zrodla = re.findall(r"@reports_bp\.route\('(/api/[^']+)'", tekst)
    ze_zrodla = [s for s in ze_zrodla if not s.startswith('/api/cron/')
                 and not s.startswith('/api/arkusz/')]
    assert sorted(ze_zrodla) == sorted(ENDPOINTY_API_STAREJ)


@pytest.mark.parametrize('sciezka', [
    '/reports/api/data', '/reports/api/export-excel',
    '/reports/api/map-statistics', '/reports/api/export-routimo',
    '/reports/api/dropdown-values/caretaker', '/reports/api/sync',
])
def test_wygasla_sesja_oddaje_json_a_nie_html(app_admina, sciezka):
    klient = app_admina.test_client()      # bez sesji
    odpowiedz = klient.get(sciezka) if 'sync' not in sciezka else klient.post(sciezka)
    assert odpowiedz.status_code == 401
    assert odpowiedz.get_json() == {'error': 'unauthorized'}


@pytest.mark.parametrize('sciezka', ['/reports/api/data',
                                     '/reports/api/map-statistics',
                                     '/reports/api/export-excel'])
def test_brak_dostepu_do_modulu_oddaje_json_403(app_bez_dostepu, sciezka):
    odpowiedz = zalogowany(app_bez_dostepu).get(sciezka)
    assert odpowiedz.status_code == 403
    assert odpowiedz.get_json() == {'error': 'module_access_denied'}


def test_strony_html_nadal_przekierowuja_zamiast_oddawac_json(app_admina):
    # as_json dotyczy WYLACZNIE endpointow API. Strona ma dalej przekierowac
    # na logowanie, bo konsumentem jest czlowiek, nie parser.
    klient = app_admina.test_client()
    for sciezka in ('/reports/', '/reports/arkusz', '/reports/analiza'):
        odpowiedz = klient.get(sciezka)
        assert odpowiedz.status_code == 302, sciezka
        assert '/login' in odpowiedz.headers['Location']


def test_cron_statusow_zostaje_na_bramce_tokenowej():
    tekst = zrodlo(TRASY_STAREJ)
    blok = tekst[tekst.index("@reports_bp.route('/api/cron/sync-statuses'"):][:200]
    assert '@cron_secret_required' in blok
    assert 'require_module_access' not in blok


# ===== nowe trasy arkusza ==============================================

@pytest.mark.parametrize('sciezka, metoda', [
    ('/reports/arkusz', 'get'),
    ('/reports/api/arkusz/dane', 'get'),
    ('/reports/api/arkusz/eksport', 'get'),
    ('/reports/api/arkusz/zapisz', 'post'),
    ('/reports/api/arkusz/pobierz', 'post'),
])
def test_kazda_nowa_trasa_ma_bramke(app_bez_dostepu, sciezka, metoda):
    odpowiedz = getattr(zalogowany(app_bez_dostepu), metoda)(sciezka)
    assert odpowiedz.status_code == 403
    if sciezka.startswith('/reports/api/'):
        assert odpowiedz.get_json() == {'error': 'module_access_denied'}


# ===== wariant rolowy ==================================================

def _zamowienie(app):
    with app.app_context():
        zam = SalesOrder(baselinker_order_id=1, date_created=date(2026, 9, 18),
                         delivery_state='śląskie', client_origin='Sklep',
                         paid_amount=Decimal('0'), balance_due=Decimal('0'))
        db.session.add(zam)
        db.session.commit()
        return zam.id


def test_handlowiec_nie_wysle_kolumny_z_baselinkera_przez_endpoint(app_handlowca):
    # ODCHYLENIE OD BRIEFU: dopisano 'bylo' (wartosc sprzed edycji, 'slaskie'
    # — ustawiona w _zamowienie). `parsuj_zmiany` wymaga tego pola dla KAZDEGO
    # zadania HTTP (straznik optymistyczny, arkusz_zapis.py) i bez niego caly
    # request konczy sie 400 zamiast dotrzec do sprawdzenia roli — brief tego
    # pola nie mial, zweryfikowane uruchomieniem.
    id_zam = _zamowienie(app_handlowca)
    odpowiedz = zalogowany(app_handlowca).post('/reports/api/arkusz/zapisz', json={
        'zmiany': [{'poziom': 'zamowienie', 'id': id_zam, 'nazwa': 'delivery_state',
                    'jest': 'mazowieckie', 'bylo': 'śląskie'}]})
    assert odpowiedz.status_code == 200
    wynik = odpowiedz.get_json()
    assert wynik['zapisane'] == 0 and wynik['odrzucone'] == 1
    assert 'administrator' in wynik['wyniki'][0]['blad']
    with app_handlowca.app_context():
        assert SalesOrder.query.get(id_zam).delivery_state == 'śląskie'


def test_handlowiec_zapisze_kolumne_crm_przez_endpoint(app_handlowca):
    # ODCHYLENIE OD BRIEFU: jak wyzej, dopisano 'bylo' ('Sklep' — wartosc
    # ustawiona w _zamowienie).
    id_zam = _zamowienie(app_handlowca)
    odpowiedz = zalogowany(app_handlowca).post('/reports/api/arkusz/zapisz', json={
        'zmiany': [{'poziom': 'zamowienie', 'id': id_zam, 'nazwa': 'client_origin',
                    'jest': 'Detal', 'bylo': 'Sklep'}]})
    assert odpowiedz.get_json()['zapisane'] == 1


def test_arkusz_handlowca_nie_deklaruje_prawa_do_wysylki(app_handlowca):
    html = zalogowany(app_handlowca).get('/reports/arkusz').get_data(as_text=True)
    assert 'data-moze-wysylac="false"' in html


def test_dekorator_uprawnien_nie_zostal_ruszony():
    # Decyzja uzytkownika 22.09.2026: ZERO zmian w silniku uprawnien.
    # Pod-uprawnienia reports.view / edit / push_bl sa poza zakresem.
    tekst = zrodlo(DEKORATOR)
    assert 'reports.push_bl' not in tekst
    assert 'reports.edit' not in tekst
    assert 'reports.view' not in tekst


# ===== STARA ZAKLADKA TYLKO DO ODCZYTU (Zadanie 14) ====================

SZABLON_STAREJ = os.path.join(KORZEN, 'modules', 'reports', 'templates', 'reports.html')
JS_STAREJ = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'reports.js')

ZABLOKOWANE = [
    '/reports/api/sync',
    '/reports/api/add-manual-row',
    '/reports/api/update-manual-row',
    '/reports/api/delete-manual-row',
    '/reports/api/sync-statuses',
    '/reports/api/sync-statuses-stream',
    '/reports/api/fetch-orders-stream',
    '/reports/api/fetch-orders-for-selection',
    '/reports/api/save-selected-orders-with-dimensions',
    '/reports/api/save-selected-orders',
    '/reports/api/save-orders-with-volumes',
]


@pytest.mark.parametrize('sciezka', ZABLOKOWANE)
def test_kazdy_post_starej_zakladki_jest_zablokowany(app_admina, sciezka):
    # „Bez mozliwosci edycji" znaczy tez „bez mozliwosci z konsoli
    # przegladarki" — blokada jest po stronie serwera, nie w interfejsie.
    odpowiedz = zalogowany(app_admina).post(sciezka, json={})
    assert odpowiedz.status_code == 409, sciezka
    dane = odpowiedz.get_json()
    assert dane['error'] == 'tylko_odczyt'
    assert 'Arkusz sprzedaży' in dane['komunikat']


def test_lista_zablokowanych_zgadza_sie_ze_zrodlem():
    from modules.reports.routers import ENDPOINTY_ZABLOKOWANE
    assert sorted('/reports' + s for s in ENDPOINTY_ZABLOKOWANE) == sorted(ZABLOKOWANE)


@pytest.mark.parametrize('sciezka', [
    '/reports/api/data', '/reports/api/map-statistics',
    '/reports/api/dropdown-values/caretaker', '/reports/api/export-routimo',
])
def test_odczyt_starej_zakladki_dziala_dalej(app_admina, sciezka):
    odpowiedz = zalogowany(app_admina).get(sciezka)
    assert odpowiedz.status_code != 409, sciezka


def test_strona_starej_zakladki_nie_pokazuje_kontrolek_zmieniajacych_dane():
    szablon = zrodlo(SZABLON_STAREJ)
    for identyfikator in ('id="syncBtn"', 'id="syncStatusesBtn"',
                          'id="addManualRowBtn"'):
        assert identyfikator not in szablon, identyfikator


def test_strona_starej_zakladki_ma_pasek_trybu_odczytu():
    szablon = zrodlo(SZABLON_STAREJ)
    assert 'tylko do odczytu' in szablon
    assert 'Arkusz sprzedaży' in szablon


def test_reports_js_nie_renderuje_przyciskow_edycji_i_usuwania():
    js = zrodlo(JS_STAREJ)
    assert 'action-btn-edit' not in js
    assert 'action-btn-delete' not in js


def test_stara_tabela_nie_jest_kasowana_zadna_migracja():
    # Skasowanie tabeli to OSOBNE zadanie po weryfikacji liczb przez
    # uzytkownika. Ten test pilnuje, ze nie zrobilismy tego przy okazji.
    katalog = os.path.join(KORZEN, 'migrations')
    for nazwa in os.listdir(katalog):
        if not nazwa.endswith('.sql'):
            continue
        with open(os.path.join(katalog, nazwa), encoding='utf-8') as plik:
            tresc = plik.read().lower()
        assert 'drop table' not in tresc or 'baselinker_reports_orders' not in tresc, nazwa


def test_cron_statusow_dziala_dalej():
    # Cron nie jest „widokiem" — odswieza statusy istniejacych wierszy
    # tokenem, bez sesji. Wylaczenie go to osobna decyzja operacyjna.
    from modules.reports.routers import ENDPOINTY_ZABLOKOWANE
    assert '/api/cron/sync-statuses' not in ENDPOINTY_ZABLOKOWANE
