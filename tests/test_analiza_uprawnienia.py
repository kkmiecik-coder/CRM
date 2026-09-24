# -*- coding: utf-8 -*-
"""Bramka odczytu na trasach Analizy sprzedazowej.

Dwa scenariusze na kazda trase: brak sesji i sesja bez dostepu do modulu.
Trasy HTML maja przekierowac albo pokazac strone odmowy, endpointy API maja
oddac JSON — nigdy HTML. Ten drugi przypadek jest tu istotny, bo dashboard
odswieza sie fetch-em: strona logowania zwrocona jako HTML wywala parser JSON-a
i uzytkownik zostaje z wiecznym szkieletem bez ani jednego komunikatu.

W minimalnym Flasku rejestrujemy zaslepki endpointow, ktorych dekorator uzywa
do przekierowan (`login`, `dashboard.dashboard`) i zaslepke access_denied.html
— inaczej padalby BuildError zamiast testowanego zachowania. Blueprint
`production` rejestrujemy NAPRAWDE, bo szablon dashboardu wola
url_for('production.static', ...) po Chart.js: bez niego /reports/analiza
oddaje 500 i testy „z uprawnieniami wszystko odpowiada 200" pada z powodu,
ktory nie ma nic wspolnego z uprawnieniami. Ten sam gotcha co w
tests/test_analiza_widok.py i tests/test_monitory_krawedzie.py:85-90.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import reports_bp
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.users.models import User, Module
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów
from modules.quotes.models import QuoteStatus
from modules.reports.models_uklad import UkladDashboardu

# ODCHYLENIE od briefu: dopisano `Module` (tabela `users_modules`). Sciezka
# „brak uprawnien" dekoratora w wariancie HTML czyta `Module.query...`, zeby
# pokazac nazwe modulu w access_denied.html — bez tabeli test wywala sie
# OperationalError zamiast testowac wlasciwe zachowanie (403).
#
# Od Planu D `/analiza` i `/api/analytics` czytaja prywatny uklad pulpitu
# (`reports_dashboard_layouts`) — to tabela TEGO modulu, wiec jest tu na
# rownych prawach z `sales_*`, inaczej niz `prod_orders` (patrz nizej).
_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Module,
    Client, Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    SalesClient, SalesOrder, SalesOrderItem, UkladDashboardu,
)]

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATYKA_PRODUKCJI = os.path.join(KORZEN, 'modules', 'production', 'static')

TRASY_HTML = ['/reports/analiza', '/reports/eksplorator', '/reports/arkusz']
# ODCHYLENIE od briefu: `/api/wartosci-wymiaru` wymaga parametru `wymiar` —
# bez niego kazde wywolanie (nawet z pelnym dostepem) dostaje 400 zly_wymiar,
# co jest zachowaniem Zadania 4/5, nie tej bramki. Dopisano wartosc, zeby test
# „z uprawnieniami wszystko odpowiada 200" mierzyl bramke, a nie walidacje.
TRASY_API = ['/reports/api/analytics', '/reports/api/eksplorator',
             '/reports/api/wartosci-wymiaru?wymiar=order_source']


def _zbuduj_app(ma_dostep):
    from modules.users.services.permission_service import PermissionService
    PermissionService.user_has_module_access = staticmethod(
        lambda user_id, module_key: ma_dostep)

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(reports_bp)

    # Zaslepki celow przekierowan dekoratora.
    app.add_url_rule('/login', 'login', lambda: 'login')
    pulpit = Blueprint('dashboard', __name__)
    pulpit.add_url_rule('/dashboard', 'dashboard', lambda: 'pulpit')
    app.register_blueprint(pulpit)
    # Szablon dashboardu wola url_for('production.static', ...) — patrz docstring.
    produkcja = Blueprint('production', __name__, static_folder=STATYKA_PRODUKCJI,
                          static_url_path='/production-static')
    app.register_blueprint(produkcja, url_prefix='/production')

    app.jinja_loader = ChoiceLoader([
        DictLoader({
            'sidebar/sidebar.html': '<nav></nav>',
            'access_denied.html': '<p>Brak dostępu do {{ module_name }}</p>',
        }),
        app.jinja_loader,
    ])
    db.init_app(app)
    return app


@pytest.fixture()
def app_z_dostepem(monkeypatch):
    from modules.users.services.permission_service import PermissionService
    oryginal = PermissionService.user_has_module_access
    app = _zbuduj_app(True)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        db.session.add(User(email='ma@woodpower.pl', password='x', role='user', active=True))
        db.session.add(User(email='nieaktywny@woodpower.pl', password='x',
                            role='user', active=False))
        db.session.commit()
        yield app
        db.session.remove()
    PermissionService.user_has_module_access = oryginal


@pytest.fixture()
def app_bez_dostepu():
    from modules.users.services.permission_service import PermissionService
    oryginal = PermissionService.user_has_module_access
    app = _zbuduj_app(False)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        db.session.add(User(email='nie@woodpower.pl', password='x', role='user', active=True))
        db.session.commit()
        yield app
        db.session.remove()
    PermissionService.user_has_module_access = oryginal


def _klient(app, email=None):
    c = app.test_client()
    if email:
        with c.session_transaction() as sesja:
            sesja['user_email'] = email
    return c


# --- brak sesji -------------------------------------------------------------

@pytest.mark.parametrize('trasa', TRASY_HTML)
def test_bez_sesji_trasa_html_przekierowuje_na_logowanie(app_z_dostepem, trasa):
    odpowiedz = _klient(app_z_dostepem).get(trasa)
    assert odpowiedz.status_code == 302
    assert '/login' in odpowiedz.headers['Location']


@pytest.mark.parametrize('trasa', TRASY_API)
def test_bez_sesji_api_oddaje_json_a_nie_strone_logowania(app_z_dostepem, trasa):
    """Bez as_json=True fetch dostalby HTML i wywalil sie na parsowaniu."""
    odpowiedz = _klient(app_z_dostepem).get(trasa)
    assert odpowiedz.status_code == 401
    assert odpowiedz.mimetype == 'application/json'
    assert odpowiedz.get_json() == {'error': 'unauthorized'}


# --- sesja bez uprawnien ----------------------------------------------------

@pytest.mark.parametrize('trasa', TRASY_HTML)
def test_bez_uprawnien_trasa_html_daje_403(app_bez_dostepu, trasa):
    odpowiedz = _klient(app_bez_dostepu, 'nie@woodpower.pl').get(trasa)
    assert odpowiedz.status_code == 403
    assert 'Brak dostępu' in odpowiedz.get_data(as_text=True)


@pytest.mark.parametrize('trasa', TRASY_API)
def test_bez_uprawnien_api_daje_403_w_json(app_bez_dostepu, trasa):
    odpowiedz = _klient(app_bez_dostepu, 'nie@woodpower.pl').get(trasa)
    assert odpowiedz.status_code == 403
    assert odpowiedz.mimetype == 'application/json'
    assert odpowiedz.get_json() == {'error': 'module_access_denied'}


# --- konto nieaktywne -------------------------------------------------------

@pytest.mark.parametrize('trasa', TRASY_API)
def test_konto_nieaktywne_dostaje_401_w_json(app_z_dostepem, trasa):
    odpowiedz = _klient(app_z_dostepem, 'nieaktywny@woodpower.pl').get(trasa)
    assert odpowiedz.status_code == 401
    assert odpowiedz.get_json() == {'error': 'unauthorized'}


# --- dostep przyznany -------------------------------------------------------

@pytest.mark.parametrize('trasa', TRASY_HTML + TRASY_API)
def test_z_uprawnieniami_wszystko_odpowiada_200(app_z_dostepem, trasa):
    assert _klient(app_z_dostepem, 'ma@woodpower.pl').get(trasa).status_code == 200


def test_analytics_nie_wymaga_tabeli_prod_orders(app_z_dostepem):
    """Regresja (Plan C, domkniecie bramki): karta mapy wojewodztw dolozyla do
    payloadu `/api/analytics` statystyke "w produkcji" liczona z `prod_orders`.
    Ta fixture bramki celowo NIE tworzy tej tabeli (patrz `_TABLES` wyzej) —
    bramka uprawnien ma sprawdzac uprawnienia, a nie zalezec od tego, czy
    modul produkcji jest juz podpiety pod baze.

    Przed naprawa: `sqlite3.OperationalError: no such table: prod_orders`
    i trasa oddawala 500 mimo poprawnych uprawnien. Test najpierw potwierdza
    zalozenie (tabeli faktycznie nie ma), zeby nie stac sie zielony z
    niewlasciwego powodu, gdyby ktos kiedys dopisal ja do `_TABLES`.
    """
    with app_z_dostepem.app_context():
        from sqlalchemy import inspect as sa_inspect
        assert not sa_inspect(db.engine).has_table('prod_orders')

    odpowiedz = _klient(app_z_dostepem, 'ma@woodpower.pl').get('/reports/api/analytics')
    assert odpowiedz.status_code == 200
    # Klucz INSTANCJI (`typ:wymiar`) — od Planu D ten sam typ karty moze stac
    # na pulpicie kilka razy.
    mapa = odpowiedz.get_json()['karty']['wojewodztwo:delivery_state']['mapa']
    # Bez tabeli produkcyjnej "w produkcji" ma wrocic jako 0 dla kazdego
    # obszaru — nie brakujacym kluczem, nie wyjatkiem zjedzonym po cichu.
    assert all(obszar['w_produkcji'] == 0 for obszar in mapa['obszary'])


# --- higiena: zadna nowa trasa nie moze zostac bez bramki -------------------

def test_kazda_trasa_modulu_analizy_ma_bramke():
    """Test rosnie razem z modulem: nowa trasa bez dekoratora oblewa go.

    Dekorator @require_module_access owija funkcje przez functools.wraps, wiec
    oryginal siedzi w __wrapped__. Brak tego atrybutu oznacza goly widok.
    """
    import modules.reports.routers_analiza as trasy

    nazwy = ['analiza', 'eksplorator', 'arkusz',
             'api_analytics', 'api_eksplorator', 'api_wartosci_wymiaru',
             # Plan D: zapis i przywrócenie prywatnego układu pulpitu.
             'api_uklad_zapisz', 'api_uklad_domyslny',
             # Plan D, Zadanie 8: fragmenty widoku (jeden kafelek, cala siatka).
             'api_kafelek', 'api_siatka']
    for nazwa in nazwy:
        widok = getattr(trasy, nazwa)
        assert hasattr(widok, '__wrapped__'), f'{nazwa} nie ma bramki uprawnien'


def test_endpointy_api_deklaruja_as_json():
    """Spec 14: as_json=True na WSZYSTKICH endpointach API (trasa '/api/...').

    Zastygla stala byla tu DWA razy: najpierw "3", potem zastapiona "7" —
    kazdy nowy endpoint API (Blok 1 Planu C dolozyl cztery, commit d56fb0c
    piaty: /api/arkusz/potwierdzenie) psul licznik z tego samego powodu i
    test trzeba bylo poprawiac recznie zamiast lapac prawdziwa regresje.
    Liczenie wystapien napisu w zrodle NIE sprawdza wlasciwej rzeczy — nie
    wiaze deklaracji as_json z KONKRETNYM endpointem, wiec nie powie, ktory
    z nich jest zly, tylko "ile ich jest".

    Naprawa: parsujemy zrodlo przez `ast` i sprawdzamy KAZDA funkcje-widok
    osobno — czy jej trasa (`@reports_bp.route(...)`) zaczyna sie od
    '/api/', i czy jej dekorator `require_module_access(...)` ma wtedy
    `as_json=True` (a trasa HTML odwrotnie — NIE powinna go miec). Test nie
    zna z gory liczby endpointow, wiec dolozenie kolejnego nie zepsuje go —
    zepsuje go tylko brakujace/bledne `as_json` na KTORYMS z nich, a wtedy
    komunikat bledu nazywa go po imieniu. NIE PRZYWRACAC liczenia po stalej
    liczbie wystapien — to ten sam blad, ktory naprawiamy trzeci raz.
    """
    import ast

    sciezka = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'modules', 'reports', 'routers_analiza.py')
    drzewo = ast.parse(open(sciezka, encoding='utf-8').read(), filename=sciezka)

    bledy = []
    znaleziono_endpoint = False

    for wezel in ast.walk(drzewo):
        if not isinstance(wezel, ast.FunctionDef):
            continue

        trasa = None
        wywolanie_bramki = None
        for dekorator in wezel.decorator_list:
            if not isinstance(dekorator, ast.Call):
                continue
            cel = dekorator.func
            if (isinstance(cel, ast.Attribute) and cel.attr == 'route'
                    and dekorator.args and isinstance(dekorator.args[0], ast.Constant)):
                trasa = dekorator.args[0].value
            elif isinstance(cel, ast.Name) and cel.id == 'require_module_access':
                wywolanie_bramki = dekorator

        if trasa is None or wywolanie_bramki is None:
            continue  # funkcja bez bramki uprawnien — pilnuje jej inny test
        znaleziono_endpoint = True

        deklaruje_as_json = any(
            slowo.arg == 'as_json' and isinstance(slowo.value, ast.Constant)
            and slowo.value.value is True
            for slowo in wywolanie_bramki.keywords
        )
        czy_api = trasa.startswith('/api/')

        if czy_api and not deklaruje_as_json:
            bledy.append(
                f"{wezel.name} (trasa {trasa}) to endpoint API, ale bramka "
                f"nie ma as_json=True — fetch dostanie HTML zamiast JSON-a")
        elif not czy_api and deklaruje_as_json:
            bledy.append(
                f"{wezel.name} (trasa {trasa}) to trasa HTML, a bramka ma "
                f"as_json=True — uzytkownik dostanie JSON zamiast strony/przekierowania")

    assert znaleziono_endpoint, 'nie znaleziono ani jednego endpointu z bramka — test nic nie sprawdzil'
    assert not bledy, 'Bledna deklaracja as_json:\n' + '\n'.join(bledy)
