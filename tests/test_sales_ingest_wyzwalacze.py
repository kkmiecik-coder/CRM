# -*- coding: utf-8 -*-
"""Dwa punkty wyzwalania zapisu do sales_*: synchronizacja produkcji
i przycisk „Pobierz zamowienia" w arkuszu.

Najwazniejszy test w tym pliku to ten, ktory dowodzi, ze AWARIA ZAPISU
DO ANALITYKI NIE WYWRACA SYNCHRONIZACJI PRODUKCJI. Produkcja to tor
krytyczny — tablety na hali — i analityka nie ma prawa jej zatrzymac.

Co jest tu podmienione i dlaczego:
  * _create_product_from_order_data — tworzenie pozycji produkcyjnej ma
    wlasne testy w tests/test_krawedzie_model.py i ciagnie parser produkcji,
    generator ID i wyliczanie deadline'u. Tutaj interesuje nas wylacznie to,
    ze produkcja zapisala SWOJE dane mimo awarii analityki.
  * ProductIDGenerator.generate_product_id_for_order — jak wyzej.
  * validate_order_products_completeness — walidacja produkcji ma wlasne
    testy; tutaj ma nie przeszkadzac.
  * _split_production_items ZOSTAJE PRAWDZIWY — na nim stoi test
    o pozycjach uslugowych.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta

import pytest
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionOrder, ProductionProduct,
    ProductionSyncLog,
)
from modules.reports import reports_bp
from modules.reports.models import BaselinkerReportOrder
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
    User, SalesClient, SalesOrder, SalesOrderItem, BaselinkerReportOrder,
    ProductionConfig, ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionSyncLog,
)]

TS_18_09 = 1789714800
BLAT = 'Blat dębowy lity A/B 100x50x2 cm'
USLUGA = 'Docięcie do wymiaru - usługa montażu'


def zamowienie(order_id=50854536, produkty=None, **nadpisania):
    baza = {
        'order_id': order_id, 'date_add': TS_18_09, 'date_confirmed': TS_18_09,
        'order_status_id': 138619, 'delivery_fullname': 'Jan Przykładowy',
        'email': 'jan.przykladowy@example.com', 'phone': '601202303',
        'delivery_postcode': '40-100', 'delivery_state': 'śląskie',
        'delivery_price': 0.0, 'payment_done': 0.0, 'order_source': 'shop',
        'custom_extra_fields': {'105623': 'Łukasz Próbny', '106169': 'netto'},
        'products': produkty if produkty is not None else [
            {'order_product_id': 991, 'quantity': 1, 'price_brutto': 800.00, 'name': BLAT},
        ],
    }
    baza.update(nadpisania)
    return baza


def _pusta_baza(app):
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)


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
def app_osobne_polaczenia(tmp_path):
    """Baza plikowa: KAZDA sesja dostaje WLASNE polaczenie.

    Domyslny `app` (SQLite w pamieci + `StaticPool`) wydaje wszystkim sesjom
    TO SAMO polaczenie DB-API — sprawdzone wykonaniem — wiec commit albo
    zamkniecie jednej sesji siega zflushowanych zmian drugiej. Na takiej
    bazie nie da sie pokazac, ze przeliczanie priorytetow pracuje na SWOJEJ
    transakcji: kazdy wynik dalby sie wytlumaczyc wspolnym polaczeniem.
    SQLite z PLIKU idzie przez `NullPool`, wiec zachowuje sie jak produkcyjny
    MySQL: osobne polaczenia, osobne transakcje.

    CENA: SQLite dopuszcza jednego pisarza naraz. Praca wolajacego w testach
    na tym fixture jest wiec DODANA DO SESJI, ale NIE zflushowana — inaczej
    trzymalaby blokade zapisu i priorytety nie mialyby gdzie pisac. Dla
    mierzonej wlasnosci (czyja transakcja zatwierdza czyja prace) to bez
    roznicy: praca niezflushowana nalezy do transakcji wolajacego tak samo
    jak zflushowana.
    """
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///%s' % (tmp_path / 'crm.sqlite')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'test'
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()
        db.engine.dispose()


@pytest.fixture()
def serwis_synchronizacji(app, monkeypatch):
    """SyncService z podmienionym tworzeniem pozycji produkcyjnych."""
    from modules.production.services import sync_service as modul
    from modules.production.services.id_generator import ProductIDGenerator

    with app.app_context():
        zamowienie_produkcyjne = ProductionOrder(
            baselinker_order_id=50854536, internal_order_number='26_00001')
        db.session.add(zamowienie_produkcyjne)
        db.session.commit()
        id_zamowienia = zamowienie_produkcyjne.id

    def fałszywe_id(baselinker_order_id, total_products_count):
        return {'product_ids': [f'26_{i:05d}' for i in range(1, total_products_count + 1)]}

    monkeypatch.setattr(ProductIDGenerator, 'generate_product_id_for_order',
                        staticmethod(fałszywe_id))
    monkeypatch.setattr(modul.BaselinkerSyncService,
                        'validate_order_products_completeness',
                        lambda self, order_data: (True, []))

    def fałszywy_produkt(self, order_data, product_data, payment_date=None,
                         sequence_number=1, id_generation_result=None,
                         sync_source='baselinker_auto', quantity=1):
        return ProductionProduct(
            order_id=id_zamowienia,
            short_product_id=f'26_{sequence_number:05d}',
            product_sequence_in_order=sequence_number,
            original_product_name=product_data.get('name', ''),
            quantity=quantity,
        )

    monkeypatch.setattr(modul.BaselinkerSyncService,
                        '_create_product_from_order_data', fałszywy_produkt)

    with app.app_context():
        yield modul.BaselinkerSyncService()


# ===== punkt wyzwalania: produkcja ======================================

def test_synchronizacja_produkcji_zasila_analityke(app, serwis_synchronizacji):
    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie()], sync_type='manual', auto_status_change=False)
        assert wynik['products_created'] == 1
        assert wynik['analityka']['nowe'] == 1
        assert wynik['analityka']['zrodlo'] == 'produkcja'
        assert SalesOrder.query.count() == 1


def _analityka_ktora_pisze_i_wybucha(zapisane):
    """Atrapa zapisu do analityki: czesciowy zapis, rollback, wyjatek.

    Najgorszy mozliwy przebieg — analityka zdazyla cos zacommitowac, potem
    cofnela wspoldzielona sesje i dopiero wtedy padla. Jesli produkcja to
    przezyje w komplecie, przezyje kazdy lagodniejszy wariant.
    """
    def wybuch(zamowienia, zrodlo='analiza'):
        zapisane['produkty_w_chwili_wywolania'] = ProductionProduct.query.count()
        db.session.add(SalesOrder(baselinker_order_id=999999,
                                  date_created=date(2026, 9, 18),
                                  customer_name='Czesciowy zapis'))
        db.session.commit()
        db.session.rollback()
        raise RuntimeError('baza analityki nie odpowiada')
    return wybuch


def test_awaria_analityki_po_czesciowym_zapisie_nie_rusza_danych_produkcji(
        app, serwis_synchronizacji, monkeypatch):
    # ZNALEZISKO WAZNE (przeglad Zadania 6): poprzednia wersja tego testu
    # uzywala atrapy rzucajacej ZANIM cokolwiek dotknelo bazy — sprawdzala
    # wiec atrape, nie system. Tutaj atrapa rzuca PO czesciowym zapisie
    # i PO `db.session.rollback()` na wspoldzielonej sesji.
    import modules.reports.ingest as ingest

    zapisane = {}
    monkeypatch.setattr(ingest, 'zapisz_zamowienia',
                        _analityka_ktora_pisze_i_wybucha(zapisane))

    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie()], sync_type='manual', auto_status_change=False)

        # ZNALEZISKO KRYTYCZNE (przeglad Zadania 6): w chwili wywolania
        # analityki produkcja ma juz WSZYSTKO ZATWIERDZONE. To jest cala
        # istota poprawki — rollback analityki nie ma czego cofnac.
        # Dawniej zaczep stal PRZED petla produkcji i widzialby tu zero.
        assert zapisane['produkty_w_chwili_wywolania'] == 1

        # Produkcja zrobila swoje i raportuje to bez zmian.
        assert wynik['success'] is True
        assert wynik['products_created'] == 1
        assert wynik['orders_processed'] == 1
        # Analityka zglosila awarie i NIE poleciala w gore.
        assert wynik['analityka']['blad'] == 'baza analityki nie odpowiada'
        assert wynik['analityka']['nowe'] == 0

    # Dowod trwalosci: nowa sesja, czyli czytamy to, co naprawde siedzi
    # w bazie, a nie to, co wisi w pamieci starej sesji.
    with app.app_context():
        db.session.remove()
        assert ProductionProduct.query.count() == 1
        assert ProductionProduct.query.one().short_product_id == '26_00001'


def test_analityka_widzi_produkcje_juz_zatwierdzona(app, serwis_synchronizacji,
                                                    monkeypatch):
    # Ten sam niezmiennik co wyzej, ale bez awarii — kolejnosc ma
    # obowiazywac takze na sciezce, ktora konczy sie powodzeniem.
    import modules.reports.ingest as ingest

    oryginal = ingest.zapisz_zamowienia
    widziane = {}

    def podgladajacy(zamowienia, zrodlo='analiza'):
        widziane['produkty'] = ProductionProduct.query.count()
        return oryginal(zamowienia, zrodlo=zrodlo)

    monkeypatch.setattr(ingest, 'zapisz_zamowienia', podgladajacy)

    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie()], sync_type='manual', auto_status_change=False)
        assert widziane['produkty'] == 1
        assert wynik['analityka']['nowe'] == 1
        assert SalesOrder.query.count() == 1


def test_niezatwierdzona_praca_wolajacego_nie_blokuje_juz_analityki(
        app, serwis_synchronizacji):
    # ZMIANA ZACHOWANIA wzgledem Zadania 4 i jest to zamierzone.
    #
    # Dawniej zaczep stal PRZED petla produkcji i dlatego musial sie
    # wycofywac, gdy wolajacy mial cos niezatwierdzonego w sesji — inaczej
    # commit analityki zatwierdzilby cudza prace. Kosztem bylo ciche
    # POMINIECIE calej paczki w analityce.
    #
    # Teraz zaczep stoi na koncu, wiec w chwili jego wywolania petla
    # produkcji dawno zamknela swoje transakcje i analityka pisze normalnie.
    # Los wiersza dodanego przez wolajacego rozstrzyga PRODUKCJA (commituje
    # po kazdym zamowieniu) — to jej wlasne, dawne zachowanie, nie skutek
    # dzialania analityki. Straznik wlasnosci sesji zyje dalej w samym
    # `ingest.zapisz_zamowienia` (tests/test_sales_ingest_zapis.py).
    with app.app_context():
        db.session.add(ProductionOrder(baselinker_order_id=999999999,
                                       internal_order_number='OBCY'))

        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie()], sync_type='manual', auto_status_change=False)

        assert wynik['analityka']['blad'] is None
        assert wynik['analityka']['nowe'] == 1
        assert SalesOrder.query.count() == 1
        assert wynik['success'] is True
        assert wynik['products_created'] == 1


def test_analityka_dostaje_pozycje_uslugowe_mimo_filtra_produkcji(
        app, serwis_synchronizacji):
    # process_orders_with_priority_logic MUTUJE order_data['products'],
    # wyrzucajac pozycje uslugowe. Analityka musi dostac komplet — usluga ma
    # w analizie wlasny group_type i wchodzi do wartosci zamowienia,
    # a wykluczana jest dopiero z metrow szesciennych.
    #
    # Ten test pilnuje ZDJECIA danych (`copy.deepcopy` przed petla). Zaczep
    # stoi teraz na KONCU metody, wiec bez tej kopii analityka dostawalaby
    # liste juz okrojona przez produkcje i cicho rozjechalaby sie
    # z BaseLinkerem.
    produkty = [
        {'order_product_id': 991, 'quantity': 1, 'price_brutto': 800.00, 'name': BLAT},
        {'order_product_id': 992, 'quantity': 1, 'price_brutto': 120.00, 'name': USLUGA},
    ]
    with app.app_context():
        serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie(produkty=produkty)], sync_type='manual', auto_status_change=False)

        pozycje = SalesOrderItem.query.order_by(SalesOrderItem.bl_order_product_id).all()
        assert len(pozycje) == 2
        assert pozycje[1].group_type == 'usługa'
        # Produkcja dostala tylko jedna pozycje — filtr dziala jak dotad.
        assert ProductionProduct.query.count() == 1


def test_synchronizacja_produkcji_nie_dotyka_starej_tabeli(app, serwis_synchronizacji):
    with app.app_context():
        serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie()], sync_type='manual', auto_status_change=False)
        assert BaselinkerReportOrder.query.count() == 0


# ===== kontrakt final_result['analityka'] ===============================
#
# ZNALEZISKO WAZNE (przeglad Zadania 4, sync_service.py:944): kontrakt
# przekazany nastepnemu zadaniu w raport-c-task-4.md ("blad is None gdy
# zapis do analizy sie powiodl [...] i wtedy pozostale liczby sa
# zerowe/puste") jest nieprawdziwy w OBIE strony. Te dwa testy dokumentuja
# prawdziwe zachowanie, zeby zadanie konsumujace ten wynik (UI wyniku
# synchronizacji) nie budowalo logiki na falszywym zalozeniu.

def test_kazde_zamowienie_pada_osobno_a_blad_i_tak_zostaje_none(
        app, serwis_synchronizacji):
    # (a) zapisz_zamowienia lapie blad PER zamowienie i nigdy nie rzuca go
    # dalej — wiec analityka['blad'] zostaje None, NAWET GDY wszystkie
    # zamowienia w paczce padly. Prawdziwy sukces to 'blad is None' ORAZ
    # 'bledy' puste, nie samo 'blad is None'.
    zle_zamowienie = zamowienie(order_id=50854537, delivery_price='nie-liczba')
    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zle_zamowienie], sync_type='manual', auto_status_change=False)

        assert wynik['analityka']['blad'] is None
        assert wynik['analityka']['nowe'] == 0
        assert len(wynik['analityka']['bledy']) == 1
        assert wynik['analityka']['bledy'][0]['order_id'] == 50854537


def test_wyjatek_po_czesciowym_zapisie_zostawia_zerowe_liczniki_mimo_zapisanego_wiersza(
        app, serwis_synchronizacji, monkeypatch):
    # (b) gdy wyjatek wyleci PO czesciowym zapisie (np. blad poza petla
    # per-zamowienie wewnatrz zapisz_zamowienia), analityka raportuje
    # 'nowe': 0, choc wiersz w sales_orders jest juz ZACOMMITOWANY. Liczniki
    # w analityka po wyjatku sa wiec niewiarygodne.
    import modules.reports.ingest as ingest

    def czesciowy_zapis_i_wybuch(zamowienia, zrodlo='analiza'):
        zam = SalesOrder(baselinker_order_id=999999, date_created=date(2026, 9, 18),
                         customer_name='Czesciowy zapis')
        db.session.add(zam)
        db.session.commit()
        raise RuntimeError('padlo po czesciowym zapisie')

    monkeypatch.setattr(ingest, 'zapisz_zamowienia', czesciowy_zapis_i_wybuch)

    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie()], sync_type='manual', auto_status_change=False)

        assert wynik['analityka']['blad'] == 'padlo po czesciowym zapisie'
        # Kontrakt "blad is None => sukces" jest zly takze w te strone:
        # liczniki po wyjatku sa zerowe, mimo ze wiersz JUZ jest w bazie.
        assert wynik['analityka']['nowe'] == 0
        assert SalesOrder.query.count() == 1


# ===== punkt wyzwalania: analiza ========================================

class AtrapaSerwisuBL:
    """Zamiast prawdziwego BaselinkerReportsService — zero ruchu sieciowego."""

    def __init__(self, orders=None, success=True, error=None):
        self.orders = orders if orders is not None else []
        self.success = success
        self.error = error
        self.wywolania = []

    def fetch_orders_from_date_range(self, date_from, date_to,
                                     get_all_statuses=False, limit_per_page=100):
        self.wywolania.append((date_from, date_to, get_all_statuses))
        return {'success': self.success, 'orders': self.orders,
                'error': self.error, 'chunks_processed': 1, 'duration_seconds': 0.1}


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


def _wczoraj_i_dzis():
    from modules.reports.analiza_service import dzis_lokalnie
    dzis = dzis_lokalnie()
    return (dzis - timedelta(days=1)).isoformat(), dzis.isoformat()


def test_pobieranie_zapisuje_do_sales_i_nie_dotyka_starej_tabeli(
        app, klient_http, monkeypatch):
    import modules.reports.routers_analiza as trasy
    atrapa = AtrapaSerwisuBL(orders=[zamowienie()])
    monkeypatch.setattr(trasy, 'get_reports_service', lambda: atrapa)

    od, do = _wczoraj_i_dzis()
    odpowiedz = klient_http.post('/reports/api/arkusz/pobierz', json={'od': od, 'do': do})

    assert odpowiedz.status_code == 200
    dane = odpowiedz.get_json()
    assert dane['pobranych'] == 1
    assert dane['zapis']['nowe'] == 1
    assert dane['zapis']['zrodlo'] == 'analiza'
    with app.app_context():
        assert SalesOrder.query.count() == 1
        assert BaselinkerReportOrder.query.count() == 0
        assert ProductionProduct.query.count() == 0


@pytest.mark.parametrize('cialo, fragment_komunikatu', [
    ({}, 'podaj zakres dat'),
    ({'od': '2026-09-01'}, 'podaj zakres dat'),
    ({'do': '2026-09-10'}, 'podaj zakres dat'),
    ({'od': '', 'do': '2026-09-10'}, 'podaj zakres dat'),
    ({'od': 'wczoraj', 'do': '2026-09-10'}, 'RRRR-MM-DD'),
    ({'od': '2026-09-10', 'do': '2026-09-01'}, 'późniejszy'),
    ({'od': '1900-01-01', 'do': '1900-03-01'}, 'wcześniejszy'),
    ({'od': '2026-01-01', 'do': '2026-09-01'}, 'dłuższy niż 92'),
])
def test_pobieranie_odrzuca_zly_zakres(klient_http, cialo, fragment_komunikatu):
    odpowiedz = klient_http.post('/reports/api/arkusz/pobierz', json=cialo)
    assert odpowiedz.status_code == 400
    dane = odpowiedz.get_json()
    assert dane['error'] == 'zly_zakres'
    assert fragment_komunikatu in dane['komunikat']


def test_pobieranie_odrzuca_zakres_z_przyszlosci(klient_http):
    from modules.reports.analiza_service import dzis_lokalnie
    jutro = (dzis_lokalnie() + timedelta(days=1)).isoformat()
    odpowiedz = klient_http.post('/reports/api/arkusz/pobierz',
                                 json={'od': jutro, 'do': jutro})
    assert odpowiedz.status_code == 400
    assert 'przyszłości' in odpowiedz.get_json()['komunikat']


def test_pobieranie_bez_ciala_zadania_zwraca_400_a_nie_500(klient_http):
    odpowiedz = klient_http.post('/reports/api/arkusz/pobierz',
                                 data='', content_type='application/json')
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zly_zakres'


def test_pobieranie_nie_odpowiada_na_get(klient_http):
    assert klient_http.get('/reports/api/arkusz/pobierz').status_code == 405


def test_blad_baselinkera_konczy_sie_502_a_nie_500(klient_http, monkeypatch):
    import modules.reports.routers_analiza as trasy
    monkeypatch.setattr(trasy, 'get_reports_service',
                        lambda: AtrapaSerwisuBL(success=False, error='API timeout'))
    od, do = _wczoraj_i_dzis()
    odpowiedz = klient_http.post('/reports/api/arkusz/pobierz', json={'od': od, 'do': do})
    assert odpowiedz.status_code == 502
    assert odpowiedz.get_json()['komunikat'] == 'API timeout'


def test_pobieranie_zwraca_json_przy_wygaslej_sesji(app, klient_http):
    with klient_http.session_transaction() as sesja:
        sesja.clear()
    od, do = _wczoraj_i_dzis()
    odpowiedz = klient_http.post('/reports/api/arkusz/pobierz', json={'od': od, 'do': do})
    assert odpowiedz.status_code == 401
    assert odpowiedz.get_json() == {'error': 'unauthorized'}


# ===== wszystkie trzy miejsca wolajace ==================================
#
# ZNALEZISKO WAZNE (przeglad Zadania 6): `process_orders_with_priority_logic`
# ma TRZECH wolajacych i tylko jeden z nich byl przetestowany. Awaria
# analityki musi byc niegrozna na KAZDEJ z tych sciezek, bo kazda konczy sie
# zapisem danych produkcji:
#   * `sync_paid_orders_only`      — cron (sync_service.py:466)
#   * `manual_sync_with_filtering` — reczna synchronizacja z panelu (:1951)
#   * `process_orders_with_priority_logic` — funkcja modulowa (:3650)


@pytest.fixture()
def bez_efektow_ubocznych_produkcji(monkeypatch):
    """Wycisza to, co na tych sciezkach wychodzi poza baze albo poza zakres.

    Zmiana statusu w BaseLinkerze to ruch sieciowy, a przeliczanie priorytetow
    ma wlasne testy i wlasny commit — tutaj interesuje nas wylacznie to, czy
    awaria analityki rusza dane produkcji.
    """
    from modules.production.services import baselinker_status_sync, priority_service

    monkeypatch.setattr(baselinker_status_sync, 'set_status_for_imported_order',
                        lambda order_id: True)

    class _AtrapaPriorytetow:
        def recalculate_all_priorities(self):
            return {'products_updated': 0, 'manual_overrides_preserved': 0}

    monkeypatch.setattr(priority_service, 'get_priority_calculator',
                        lambda: _AtrapaPriorytetow())


def _liczby_produkcji(wynik):
    """(sukces, zamowien, produktow) — trzej wolajacy maja rozne ksztalty wyniku."""
    dane = wynik['data']['stats'] if 'data' in wynik else wynik
    return wynik['success'], dane['orders_processed'], dane['products_created']


def _uruchom_cron(serwis, monkeypatch):
    """Sciezka crona: sync_paid_orders_only (sync_service.py:466)."""
    monkeypatch.setattr(type(serwis), '_fetch_paid_orders_for_cron',
                        lambda self: [zamowienie()])
    return serwis.sync_paid_orders_only()


def _uruchom_reczna(serwis, monkeypatch):
    """Sciezka recznej synchronizacji z panelu (sync_service.py:1951)."""
    import modules.reports.service as serwis_raportow

    monkeypatch.setattr(serwis_raportow, 'get_reports_service',
                        lambda: AtrapaSerwisuBL(orders=[zamowienie()]))
    return serwis.manual_sync_with_filtering({
        'target_statuses': [138619],
        'force_update': True,
        'auto_status_change': False,
        'recalculate_priorities': False,
    })


def _uruchom_funkcje_modulowa(serwis, monkeypatch):
    """Funkcja modulowa process_orders_with_priority_logic (:3650)."""
    from modules.production.services import sync_service as modul

    monkeypatch.setattr(modul, '_sync_service_instance', serwis)
    return modul.process_orders_with_priority_logic(
        [zamowienie()], sync_type='manual', auto_status_change=False)


@pytest.mark.parametrize('uruchom', [_uruchom_cron, _uruchom_reczna,
                                     _uruchom_funkcje_modulowa],
                         ids=['cron', 'reczna', 'funkcja_modulowa'])
def test_awaria_analityki_nie_rusza_produkcji_na_kazdej_sciezce(
        app, serwis_synchronizacji, bez_efektow_ubocznych_produkcji,
        monkeypatch, uruchom):
    import modules.reports.ingest as ingest

    zapisane = {}
    monkeypatch.setattr(ingest, 'zapisz_zamowienia',
                        _analityka_ktora_pisze_i_wybucha(zapisane))

    with app.app_context():
        wynik = uruchom(serwis_synchronizacji, monkeypatch)

        # Produkcja zapisala swoje i zaraportowala to bez zmian.
        udalo_sie, zamowien, produktow = _liczby_produkcji(wynik)
        assert produktow == 1
        assert zamowien == 1
        assert udalo_sie is True
        # W chwili wywolania analityki produkcja byla juz zatwierdzona,
        # wiec jej rollback nie mial czego cofnac.
        assert zapisane['produkty_w_chwili_wywolania'] == 1

    with app.app_context():
        db.session.remove()
        assert ProductionProduct.query.count() == 1


@pytest.mark.parametrize('uruchom', [_uruchom_cron, _uruchom_reczna,
                                     _uruchom_funkcje_modulowa],
                         ids=['cron', 'reczna', 'funkcja_modulowa'])
def test_kazda_sciezka_zasila_analityke_gdy_nic_nie_pada(
        app, serwis_synchronizacji, bez_efektow_ubocznych_produkcji,
        monkeypatch, uruchom):
    # Kontrola pozytywna do testu wyzej: osłona ma lapac awarie, a nie
    # wylaczac zapis do analityki na ktorejkolwiek ze sciezek.
    with app.app_context():
        uruchom(serwis_synchronizacji, monkeypatch)
        assert SalesOrder.query.count() == 1
        assert SalesOrder.query.one().baselinker_order_id == 50854536


# ===== izolacja sesji: analityka nie wspoldzieli transakcji z produkcja ==
#
# DOWOD KONTROLI ADWERSARYJNEJ (22.09.2026). Petla produkcji ma galezie,
# ktore ANI nie commituja, ANI nie rollbackuja:
#   * „Brak produktow do zapisania" (sync_service.py:884),
#   * `except Exception as item_error` (sync_service.py:825).
# W obu przypadkach `_create_production_product_from_data` zdazylo juz zrobic
# `db.session.add(ProductionOrder)` + `db.session.flush()`
# (sync_service.py:1689-1702), a `ProductionConfiguration.find_or_create`
# flushuje w models.py:121-122. Praca produkcji jest wiec ZFLUSHOWANA
# I NIEZACOMMITOWANA w chwili, gdy startuje zaczep analityki.
#
# Analityka przy bledzie wola `db.session.rollback()` — wlasny
# (sync_service.py:969) albo ten wewnatrz `zapisz_zamowienia` — i KASUJE
# ta prace. Straznik `sesja_bez_cudzych_zmian()` tego nie lapal, bo po
# `flush()` zbiory `db.session.new/dirty/deleted` sa PUSTE.
#
# Rozstrzygniecie: analityka pracuje na WLASNEJ sesji i nigdy nie dotyka
# `db.session`.

BL_BEZ_POZYCJI = 50854537


def _zbuduj_produkcje_flushujaca_bez_commita(monkeypatch):
    """Cialo obu fixture'ow ponizej — patrz `produkcja_flushujaca_bez_commita`."""
    from modules.production.services import sync_service as modul
    from modules.production.services.id_generator import ProductIDGenerator

    def falszywe_id(baselinker_order_id, total_products_count):
        return {'product_ids': ['26_%05d' % i
                                for i in range(1, total_products_count + 1)]}

    monkeypatch.setattr(ProductIDGenerator, 'generate_product_id_for_order',
                        staticmethod(falszywe_id))
    monkeypatch.setattr(modul.BaselinkerSyncService,
                        'validate_order_products_completeness',
                        lambda self, order_data: (True, []))

    def falszywy_produkt(self, order_data, product_data, payment_date=None,
                         sequence_number=1, id_generation_result=None,
                         sync_source='baselinker_auto', quantity=1):
        bl_id = order_data.get('order_id')
        zamowienie_prod = ProductionOrder.query.filter_by(
            baselinker_order_id=bl_id).first()
        if zamowienie_prod is None:
            zamowienie_prod = ProductionOrder(
                baselinker_order_id=bl_id,
                internal_order_number='26_%s' % bl_id)
            db.session.add(zamowienie_prod)
        db.session.flush()   # jak sync_service.py:1702 — po to, zeby miec id
        if bl_id == BL_BEZ_POZYCJI:
            return None      # -> galaz „Brak produktow do zapisania"
        return ProductionProduct(
            order_id=zamowienie_prod.id,
            short_product_id='26_%05d' % sequence_number,
            product_sequence_in_order=sequence_number,
            original_product_name=product_data.get('name', ''),
            quantity=quantity,
        )

    monkeypatch.setattr(modul.BaselinkerSyncService,
                        '_create_product_from_order_data', falszywy_produkt)

    return modul.BaselinkerSyncService


@pytest.fixture()
def produkcja_flushujaca_bez_commita(app, monkeypatch):
    """SyncService odtwarzajacy ZASTANY stan dyscypliny transakcyjnej produkcji.

    Atrapa `_create_product_from_order_data` robi to samo, co prawdziwy
    `_create_production_product_from_data`: upsertuje `ProductionOrder`
    i FLUSHUJE go, zeby miec `order.id`. Dla zamowienia `BL_BEZ_POZYCJI`
    zwraca `None`, wiec petla konczy to zamowienie galezia „Brak produktow
    do zapisania" — bez commita i bez rollbacku.

    Efekt: po petli w sesji wisi zflushowany, NIEZACOMMITOWANY
    `ProductionOrder(BL_BEZ_POZYCJI)`. Dokladnie w tym stanie zaczep
    analityki zastaje produkcje na serwerze produkcyjnym.
    """
    klasa = _zbuduj_produkcje_flushujaca_bez_commita(monkeypatch)
    with app.app_context():
        yield klasa()


@pytest.fixture()
def produkcja_flushujaca_na_osobnych_polaczeniach(app_osobne_polaczenia, monkeypatch):
    """To samo, ale na bazie, gdzie kazda sesja ma WLASNE polaczenie.

    Potrzebne wszedzie tam, gdzie w tle rusza przeliczanie priorytetow:
    pracuje ono na wlasnej sesji, a na `StaticPool` jej zamkniecie cofneloby
    zflushowana prace produkcji — artefakt harnessu, ktorego na produkcyjnym
    MySQL-u nie ma.
    """
    klasa = _zbuduj_produkcje_flushujaca_bez_commita(monkeypatch)
    with app_osobne_polaczenia.app_context():
        yield klasa()


def _numery_zamowien_produkcji():
    return sorted(numer for (numer,) in db.session.query(
        ProductionOrder.baselinker_order_id).all())


def test_awaria_analityki_nie_kasuje_zflushowanej_pracy_produkcji(
        app_osobne_polaczenia, produkcja_flushujaca_na_osobnych_polaczeniach,
        monkeypatch):
    """Tor krytyczny: analityka nie ma prawa cofnac pracy produkcji.

    Zmierzone przez kontrole adwersaryjna na kodzie sprzed poprawki:
    bez zaczepu w `prod_orders` zostaja [50854536, 50854537], z awaria
    analityki zostaje samo [50854536].

    Fixture z OSOBNYMI polaczeniami, bo w tej sciezce rusza tez przeliczanie
    priorytetow — a ono pracuje na wlasnej sesji (patrz nizej).
    """
    import modules.reports.ingest as ingest

    def analityka_pada(zamowienia, zrodlo='analiza'):
        raise RuntimeError('baza analityki nie odpowiada')

    monkeypatch.setattr(ingest, 'zapisz_zamowienia', analityka_pada)

    with app_osobne_polaczenia.app_context():
        wynik = produkcja_flushujaca_na_osobnych_polaczeniach.process_orders_with_priority_logic(
            [zamowienie(), zamowienie(order_id=BL_BEZ_POZYCJI)],
            sync_type='manual', auto_status_change=False)

        # Pierwsze zamowienie zapisane i zacommitowane, drugie zostawilo
        # zflushowana prace bez commita — to jest ZASTANY stan produkcji,
        # ktorego ta zmiana swiadomie NIE naprawia.
        assert wynik['products_created'] == 1
        assert _numery_zamowien_produkcji() == [50854536, BL_BEZ_POZYCJI]

        # Wolajacy (np. `sync_paid_orders_only` commitujacy `sync_log`)
        # domyka transakcje — zflushowana praca ma sie w niej znalezc.
        db.session.commit()
        db.session.remove()
        assert _numery_zamowien_produkcji() == [50854536, BL_BEZ_POZYCJI]


def _szpieg_sesji(monkeypatch):
    """Podglada `commit()` i `rollback()` na WSPOLDZIELONEJ `db.session`.

    Szpiegujemy prawdziwy obiekt `Session` spod rejestru `scoped_session`,
    bo analityka po poprawce ma miec WLASNA sesje — spy zalozony na klasie
    `Session` nie odroznilby jednej od drugiej.
    """
    wolania = []
    sesja = db.session()
    for nazwa in ('commit', 'rollback'):
        oryginal = getattr(sesja, nazwa)

        def opakowanie(_oryginal=oryginal, _nazwa=nazwa):
            wolania.append(_nazwa)
            return _oryginal()

        monkeypatch.setattr(sesja, nazwa, opakowanie)
    return wolania


def test_analityka_nie_dotyka_wspoldzielonej_sesji_nawet_gdy_zamowienie_pada(
        app, produkcja_flushujaca_bez_commita, monkeypatch):
    """Sedno kontraktu: ani `commit()`, ani `rollback()` na `db.session`.

    Na SQLite ze `StaticPool` obie sesje dostaja to samo polaczenie DB-API,
    wiec IZOLACJI TRANSAKCJI w tescie wykazac sie nie da — mozna natomiast
    przybic deterministycznie to, co jest jej warunkiem koniecznym: sciezka
    analityki nie wola na wspolnej sesji ani commita, ani rollbacku.

    Paczka jest celowo mieszana: jedno zamowienie poprawne (sciezka commita)
    i jedno felerne (sciezka rollbacku w `zapisz_zamowienia`).
    """
    with app.app_context():
        wolania = _szpieg_sesji(monkeypatch)

        # Paczka musi zawierac zamowienie, ktore produkcja ZAPISZE — inaczej
        # produkcja sama nie zawola commita i kontrola szpiega nizej nic nie
        # znaczy.
        produkcja_flushujaca_bez_commita.process_orders_with_priority_logic(
            [zamowienie(), zamowienie(order_id=BL_BEZ_POZYCJI)],
            sync_type='manual', auto_status_change=False)
        wolania_produkcji = list(wolania)

        del wolania[:]
        from modules.reports import ingest as analiza_ingest
        analiza_ingest.zapisz_zamowienia(
            [zamowienie(), zamowienie(order_id=50854538,
                                      delivery_price='nie-liczba')],
            zrodlo='produkcja')

        assert wolania == [], (
            'analityka ruszyla wspoldzielona sesje: ' + repr(wolania))
        # Kontrola poprawnosci szpiega: produkcja tej samej sesji UZYWA,
        # wiec pusta lista wyzej nie bierze sie z zepsutego podgladu.
        assert wolania_produkcji != []


def test_udany_zapis_analityki_nie_zatwierdza_pracy_produkcji(
        app, produkcja_flushujaca_bez_commita, monkeypatch):
    """Drugi kierunek tej samej dziury.

    Wspoldzielona sesja dzialala w obie strony: `db.session.commit()`
    analityki ZATWIERDZAL prace produkcji, ktorej produkcja swiadomie nie
    zacommitowala (galaz „Brak produktow do zapisania"). Miara jest ta sama:
    zero wywolan commita na `db.session` ze strony analityki.
    """
    with app.app_context():
        # Produkcja zostawia zflushowana, niezacommitowana prace.
        produkcja_flushujaca_bez_commita.process_orders_with_priority_logic(
            [zamowienie(order_id=BL_BEZ_POZYCJI)],
            sync_type='manual', auto_status_change=False)

        wolania = _szpieg_sesji(monkeypatch)
        from modules.reports import ingest as analiza_ingest
        stat = analiza_ingest.zapisz_zamowienia([zamowienie()], zrodlo='produkcja')

        assert stat['nowe'] == 1          # analityka NAPRAWDE zapisala
        assert 'commit' not in wolania    # ...i nie zrobila tego cudza reka


# ===== brudna sesja po nieudanych priorytetach nie gasi analityki =======


class _PriorytetyKtorePadajaBrudzac:
    """Kalkulator priorytetow, ktory zostawia po sobie BRUDNA `db.session`.

    Tak zachowywal sie `recalculate_all_priorities` przed poprawka: jego
    KROK 2 zmienial obiekty ORM-a, a sciezka bledu nie robila rollbacku.
    Dopoki analityka pisala po wspoldzielonej sesji, jej straznik odrzucal
    wtedy CALA paczke i liczyl ja jako pominieta — zasilanie analityki
    z produkcji przestawalo dzialac BEZ widocznego bledu.
    """

    def recalculate_all_priorities(self):
        produkt = ProductionProduct.query.first()
        if produkt is not None:
            produkt.thickness_group = '2.6-3.5'   # sesja robi sie brudna
        return {'success': False, 'error': 'sztuczna awaria priorytetow'}


# ===== wlasnosc sesji: priorytety nie commituja cudzej transakcji =======
#
# ZNALEZISKO KRYTYCZNE (kontrola adwersaryjna 22.09.2026, trzecie podejscie).
# Dwie poprzednie proby leczyly objaw. Punkt kontrolny (SAVEPOINT) bronil
# wolajacego przed COFNIECIEM jego pracy, ale nie przed jej ZATWIERDZENIEM,
# a KROK 8 commitowal WSPOLDZIELONA sesje — wiec wszystko, co wolajacy
# zostawil niezacommitowane, wjezdzalo do bazy razem z priorytetami. Do tego
# zostawalo OKNO miedzy zwolnieniem punktu a zatwierdzeniem transakcji,
# w ktorym galaz bledu nie miala juz czego wycofac: metoda meldowala porazke,
# a jej praca i tak ladowala w bazie.
#
# Rozstrzygniecie jest to samo, co dla analityki sprzedazowej
# (`ingest.zapisz_zamowienia`, sekcja "WLASNOSC SESJI"): przeliczanie
# priorytetow pracuje na WLASNEJ sesji i nie tyka `db.session` ani commitem,
# ani rollbackiem, ani punktem kontrolnym.
#
# JAK TO MIERZYMY. Te testy jada na `app_osobne_polaczenia` — bazie, w ktorej
# kazda sesja dostaje wlasne polaczenie, tak jak na produkcyjnym MySQL-u.
# Na domyslnym `app` (SQLite w pamieci + `StaticPool`) obie sesje dziela
# JEDNO polaczenie DB-API, wiec kazdy wynik dalby sie wytlumaczyc harnessem,
# a nie kodem. Praca wolajacego jest tu DODANA DO SESJI, ale nie zflushowana
# — uzasadnienie przy fixture.


def _kolejka_z_jedna_pozycja():
    """Zamowienie + pozycja w kolejce, ZACOMMITOWANE. Zwraca pozycje."""
    zamowienie_prod = ProductionOrder(baselinker_order_id=50854536,
                                      internal_order_number='26_00001')
    db.session.add(zamowienie_prod)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=zamowienie_prod.id, short_product_id='26_00001',
        product_sequence_in_order=1, original_product_name=BLAT,
        quantity=1, parsed_thickness_cm=3.0, thickness_group=None,
        current_status='czeka_na_wyciecie')
    db.session.add(produkt)
    db.session.commit()
    # Atrybuty wczytujemy TERAZ, dopoki sesja wolajacego nie ma nic wlasnego.
    # Inaczej pierwsze siegniecie po atrybut wygaszonej pozycji w trakcie
    # przeliczania pociagneloby AUTOFLUSH sesji wolajacego — czyli
    # zflushowaloby dokladnie te prace, ktorej los mierzymy.
    db.session.refresh(produkt)
    return produkt


def _scena_priorytetow(monkeypatch):
    """Stan wyjsciowy wspolny dla czterech scenariuszy. Zwraca szpiega sesji.

    Po wyjsciu: w kolejce jedna pozycja (zacommitowana), a w sesji wolajacego
    wisi jego wlasne zamowienie, ktorego on jeszcze NIE zatwierdzil.
    """
    from modules.production.services.priority_service import NewPriorityCalculator

    produkt = _kolejka_z_jedna_pozycja()

    # Praca WOLAJACEGO, ktorej on sam jeszcze nie zatwierdzil.
    db.session.add(ProductionOrder(baselinker_order_id=BL_BEZ_POZYCJI,
                                   internal_order_number='OBCY'))

    # Zapytanie produkcyjne uzywa `func.isnull` (MySQL) — na SQLite by padlo,
    # a tu chodzi o zakres transakcji, nie o tresc zapytania.
    monkeypatch.setattr(NewPriorityCalculator,
                        'get_active_products_for_prioritization',
                        lambda self: [produkt])

    return _szpieg_sesji(monkeypatch)


def _zamowienia_zatwierdzone_w_bazie():
    """Numery zamowien widoczne Z INNEGO POLACZENIA — czyli NAPRAWDE zapisane.

    Osobne polaczenie widzi wylacznie to, co zostalo zatwierdzone; praca
    wiszaca w sesji wolajacego jest dla niego niewidoczna. To jest miara
    zdania „wolajacy tego jeszcze nie zatwierdzil".
    """
    with db.engine.connect() as polaczenie:
        return sorted(numer for (numer,) in polaczenie.execute(
            db.text('SELECT baselinker_order_id FROM prod_orders')))


def _sprawdz_raport_zgadza_sie_z_baza(wynik):
    """Co przeliczanie ZGLOSILO, to ma byc w bazie — i nic ponadto.

    Na tym polegalo okno miedzy zwolnieniem punktu kontrolnego
    a zatwierdzeniem transakcji: metoda meldowala porazke, a jej zflushowana
    praca i tak wjezdzala do bazy pierwszym commitem WOLAJACEGO.
    """
    zapisany = ProductionProduct.query.one()
    if wynik['success']:
        assert zapisany.priority_rank == 1
        assert zapisany.thickness_group == '2.6-3.5'
    else:
        assert zapisany.priority_rank is None
        assert zapisany.thickness_group is None


def test_udane_priorytety_nie_zatwierdzaja_pracy_wolajacego(
        app_osobne_polaczenia, monkeypatch):
    """SCIEZKA POWODZENIA — najgrozniejsza z trzech.

    Wolajacy zostawia prace, ktorej SWIADOMIE nie zatwierdzil (tak konczy sie
    galaz "Brak produktow do zapisania" w petli `SyncService`). KROK 8
    commitowal wspoldzielona sesje, wiec udane przeliczanie priorytetow
    zatwierdzalo te prace za niego. Zmierzone na kodzie sprzed poprawki:
    zamowienie "OBCY" widac w bazie, zanim wolajacy cokolwiek zatwierdzil.
    """
    from modules.production.services.priority_service import NewPriorityCalculator

    with app_osobne_polaczenia.app_context():
        wolania = _scena_priorytetow(monkeypatch)

        wynik = NewPriorityCalculator().recalculate_all_priorities()
        # Szpieg musi zostac odczytany PRZED commitem wolajacego — inaczej
        # zliczylby takze commit, ktory wolajacy robi sam.
        wolania_przeliczania = list(wolania)

        assert wynik['success'] is True
        assert wynik['products_prioritized'] == 1

        # SEDNO: praca wolajacego ma byc NADAL niezatwierdzona.
        assert _zamowienia_zatwierdzone_w_bazie() == [50854536]

        # (b) wolajacy moze domknac WLASNA transakcje
        db.session.commit()
        db.session.remove()

        # (a) dane wolajacego w komplecie
        assert _numery_zamowien_produkcji() == [50854536, BL_BEZ_POZYCJI]
        # ...a priorytety zapisaly swoje (kontrola pozytywna: "naprawa"
        # polegajaca na tym, ze metoda przestaje cokolwiek zapisywac,
        # ma nie przejsc).
        _sprawdz_raport_zgadza_sie_z_baza(wynik)
        assert wolania_przeliczania == []


class _DrugiCommitWspolnejSesjiPada:
    """Drugie `db.session.commit()` pada — dokladnie w OKNIE.

    Pierwsze wolanie zwalnialo SAVEPOINT, drugie zatwierdzalo transakcje.
    Miedzy nimi galaz bledu nie miala juz czego wycofac, wiec zflushowana
    praca priorytetow zostawala w cudzej sesji i wjezdzala do bazy commitem
    WOLAJACEGO. Po poprawce przeliczanie nie commituje wspoldzielonej sesji
    ani razu, wiec pierwszym (i jedynym) jej commitem jest commit wolajacego
    — i ten ma sie udac.
    """

    def __init__(self, oryginal):
        self._oryginal = oryginal
        self.wolania = 0

    def __call__(self):
        self.wolania += 1
        if self.wolania == 2:
            raise RuntimeError('awaria w oknie miedzy punktem a commitem')
        return self._oryginal()


def test_awaria_w_oknie_nie_zostawia_pracy_priorytetow_w_cudzej_sesji(
        app_osobne_polaczenia, monkeypatch):
    """OKNO miedzy zwolnieniem punktu kontrolnego a zatwierdzeniem transakcji.

    Zmierzone na kodzie sprzed poprawki: `success` False, a w bazie i tak
    laduje `priority_rank=1` i `thickness_group='2.6-3.5'` — wolajacy swoim
    commitem zatwierdza NASZA prace, o ktorej wlasnie uslyszal, ze sie
    nie udala.
    """
    from modules.production.services.priority_service import NewPriorityCalculator

    with app_osobne_polaczenia.app_context():
        wolania = _scena_priorytetow(monkeypatch)
        sesja = db.session()
        monkeypatch.setattr(sesja, 'commit',
                            _DrugiCommitWspolnejSesjiPada(sesja.commit))

        wynik = NewPriorityCalculator().recalculate_all_priorities()
        wolania_przeliczania = list(wolania)

        # (b) wolajacy domyka WLASNA transakcje
        db.session.commit()
        db.session.remove()

        # SEDNO: raport ma sie zgadzac z baza. Nic, o czym metoda powiedziala
        # "nie udalo sie", nie moze zostac w cudzej sesji do zatwierdzenia.
        _sprawdz_raport_zgadza_sie_z_baza(wynik)
        # (a) dane wolajacego w komplecie
        assert _numery_zamowien_produkcji() == [50854536, BL_BEZ_POZYCJI]
        # Okna nie ma, bo nie ma czego zwalniac ani zatwierdzac na cudzej sesji.
        assert wolania_przeliczania == []


class _AwariaZatwierdzaniaWSterowniku:
    """Pierwszy COMMIT po uzbrojeniu pada na poziomie STEROWNIKA bazy.

    To prawdziwa awaria zatwierdzania — zerwane polaczenie, zakleszczenie —
    a nie wyjatek Pythona podstawiony pietro wyzej: zapis zdazyl sie
    zflushowac, a sam COMMIT nie doszedl do skutku. Pada tylko raz, bo
    kolejny commit nalezy juz do WOLAJACEGO i caly test jest o tym, czy
    wolajacy domknie wlasna transakcje.
    """

    def __init__(self, dialekt):
        self._oryginal = dialekt.do_commit
        self._klasa_bledu = dialekt.dbapi.OperationalError
        self.uzbrojony = False

    def __call__(self, polaczenie):
        if self.uzbrojony:
            self.uzbrojony = False
            raise self._klasa_bledu('zakleszczenie przy COMMIT (symulacja)')
        return self._oryginal(polaczenie)


def test_awaria_commitu_w_sterowniku_nie_zabiera_wolajacemu_transakcji(
        app_osobne_polaczenia, monkeypatch):
    """PRAWDZIWA awaria COMMIT-u wstrzyknieta w `dialect.do_commit`.

    Zmierzone na kodzie sprzed poprawki: awaria zabiera wolajacemu transakcje
    RAZEM z jego praca — `db.session` jest zdezaktywowana i kazda kolejna
    operacja wolajacego konczy sie `PendingRollbackError`.
    """
    from modules.production.services.priority_service import NewPriorityCalculator

    with app_osobne_polaczenia.app_context():
        wolania = _scena_priorytetow(monkeypatch)
        awaria = _AwariaZatwierdzaniaWSterowniku(db.engine.dialect)
        monkeypatch.setattr(db.engine.dialect, 'do_commit', awaria)

        awaria.uzbrojony = True
        wynik = NewPriorityCalculator().recalculate_all_priorities()
        wolania_przeliczania = list(wolania)

        assert awaria.uzbrojony is False, 'awaria COMMIT-u nie zostala wystrzelona'
        assert wynik['success'] is False

        # (b) SEDNO: sesja wolajacego nie jest zablokowana
        db.session.commit()
        db.session.remove()

        # (a) dane wolajacego w komplecie
        assert _numery_zamowien_produkcji() == [50854536, BL_BEZ_POZYCJI]
        _sprawdz_raport_zgadza_sie_z_baza(wynik)
        assert wolania_przeliczania == []


def test_nieudane_priorytety_sprzataja_po_sobie_a_nie_po_wolajacym(
        app_osobne_polaczenia, monkeypatch):
    """Awaria w polowie drogi: priorytety cofaja WLASNA prace, nie cudza.

    ZNALEZISKO WAZNE (kontrola adwersaryjna 22.09.2026, regresja wlasna):
    galaz bledu dostala kiedys `db.session.rollback()`, zeby nie zostawiac
    po sobie brudnej sesji. Intencja byla sluszna, ale rollback
    na wspoldzielonej sesji cofa CALA transakcje — razem z praca wolajacego.
    Po przejsciu na wlasna sesje nie ma juz czym tego zrobic.
    """
    from modules.production.services.priority_service import NewPriorityCalculator

    with app_osobne_polaczenia.app_context():
        wolania = _scena_priorytetow(monkeypatch)

        def wybuch(self, produkty):
            raise RuntimeError('sztuczna awaria priorytetow')

        # Blad leci PO KROKU 2, ktory zdazyl juz pozmieniac obiekty ORM-a.
        monkeypatch.setattr(NewPriorityCalculator, 'group_products_by_weeks',
                            wybuch)

        wynik = NewPriorityCalculator().recalculate_all_priorities()
        wolania_przeliczania = list(wolania)

        assert wynik['success'] is False
        assert 'sztuczna awaria priorytetow' in wynik['error']

        # (b) wolajacy domyka WLASNA transakcje
        db.session.commit()
        db.session.remove()

        # (a) dane wolajacego w komplecie
        assert _numery_zamowien_produkcji() == [50854536, BL_BEZ_POZYCJI]
        # ...a wlasna, nieudana praca priorytetow ma byc cofnieta.
        _sprawdz_raport_zgadza_sie_z_baza(wynik)
        assert wolania_przeliczania == []


def test_udane_priorytety_nadal_zapisuja_swoja_prace(
        app_osobne_polaczenia, monkeypatch):
    # Kontrola pozytywna: "naprawa" polegajaca na tym, ze przeliczanie
    # priorytetow przestaje cokolwiek zapisywac, ma nie przejsc.
    from modules.production.services.priority_service import NewPriorityCalculator

    with app_osobne_polaczenia.app_context():
        produkt = _kolejka_z_jedna_pozycja()
        monkeypatch.setattr(NewPriorityCalculator,
                            'get_active_products_for_prioritization',
                            lambda self: [produkt])

        wynik = NewPriorityCalculator().recalculate_all_priorities()
        assert wynik['success'] is True
        assert wynik['products_prioritized'] == 1

        db.session.remove()
        zapisany = ProductionProduct.query.one()
        assert zapisany.priority_rank == 1
        assert zapisany.thickness_group == '2.6-3.5'


def test_brudna_sesja_po_priorytetach_nie_blokuje_zasilania_analityki(
        app, serwis_synchronizacji, monkeypatch):
    from modules.production.services import priority_service

    monkeypatch.setattr(priority_service, 'get_priority_calculator',
                        lambda: _PriorytetyKtorePadajaBrudzac())

    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie()], sync_type='manual', auto_status_change=False)

        assert wynik['analityka']['nowe'] == 1
        assert wynik['analityka']['ostrzezenie'] is None
        db.session.remove()
        assert SalesOrder.query.count() == 1


# ===== koniec z cichym pomijaniem =======================================
#
# ZNALEZISKO (kontrola adwersaryjna 22.09.2026): utrata danych byla CICHA.
# Gdy blad obsluzylo wnetrze `zapisz_zamowienia`, funkcja konczyla sie
# „sukcesem" — `success` produkcji True, `blad` None — a informacja siedziala
# wylacznie w liscie `bledy`, ktorej nie widzial ani operator, ani log crona.


def test_pominiete_zamowienia_widac_w_wyniku_synchronizacji(
        app, serwis_synchronizacji):
    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie(), zamowienie(order_id=50854538,
                                      delivery_price='nie-liczba')],
            sync_type='manual', auto_status_change=False)

        # Produkcja raportuje swoje bez zmian — analityka nie ma prawa
        # oznaczac synchronizacji produkcji jako nieudanej.
        assert wynik['success'] is True
        assert wynik['products_created'] == 2

        ostrzezenie = wynik['analityka_ostrzezenie']
        assert ostrzezenie, 'niepelny zapis do analityki przeszedl po cichu'
        assert 'bledow 1' in ostrzezenie
        assert wynik['analityka']['ostrzezenie'] == ostrzezenie


def test_ostrzezenie_analityki_dochodzi_do_wyniku_crona(
        app, serwis_synchronizacji, bez_efektow_ubocznych_produkcji, monkeypatch):
    # Cron nie ma operatora — jedyne, co po nim zostaje, to linia logu
    # i zwrocony slownik. Ostrzezenie musi byc w obu.
    monkeypatch.setattr(type(serwis_synchronizacji), '_fetch_paid_orders_for_cron',
                        lambda self: [zamowienie(order_id=50854538,
                                                 delivery_price='nie-liczba')])

    with app.app_context():
        wynik = serwis_synchronizacji.sync_paid_orders_only()

        assert wynik['success'] is True
        assert 'bledow 1' in (wynik['analityka_ostrzezenie'] or '')


def test_ostrzezenie_analityki_dochodzi_do_wyniku_recznej_synchronizacji(
        app, serwis_synchronizacji, bez_efektow_ubocznych_produkcji, monkeypatch):
    # ZNALEZISKO WAZNE (kontrola adwersaryjna 22.09.2026): reczne „Pobierz
    # zamowienia" z panelu produkcji czytalo z wyniku przetwarzania WYLACZNIE
    # liczniki (orders_processed, products_created, errors_count) i gubilo
    # `analityka_ostrzezenie`. Ta sciezka ma operatora przed ekranem — a on
    # jako jedyny nie dowiadywal sie, ze analityka pominela zamowienia.
    import modules.reports.service as serwis_raportow

    monkeypatch.setattr(
        serwis_raportow, 'get_reports_service',
        lambda: AtrapaSerwisuBL(orders=[zamowienie(order_id=50854538,
                                                   delivery_price='nie-liczba')]))

    with app.app_context():
        wynik = serwis_synchronizacji.manual_sync_with_filtering({
            'target_statuses': [138619],
            'force_update': True,
            'auto_status_change': False,
            'recalculate_priorities': False,
        })

        # Produkcja raportuje swoje bez zmian.
        assert wynik['success'] is True
        assert wynik['data']['stats']['products_created'] == 1

        ostrzezenie = wynik['analityka_ostrzezenie']
        assert ostrzezenie, 'niepelny zapis do analityki przeszedl po cichu'
        assert 'bledow 1' in ostrzezenie
        # Operator patrzy na dziennik synchronizacji w panelu — ostrzezenie
        # ma byc takze tam, inaczej „dotarlo do wyniku" znaczy „nikt tego
        # nie zobaczy".
        poziomy = [wpis['level'] for wpis in wynik['data']['log_entries']
                   if ostrzezenie in wpis['message']]
        assert poziomy == ['warning']


def test_reczna_synchronizacja_bez_ostrzezenia_gdy_analityka_zapisala_komplet(
        app, serwis_synchronizacji, bez_efektow_ubocznych_produkcji, monkeypatch):
    # Kontrola pozytywna: klucz ma byc w wyniku ZAWSZE, a None znaczy
    # „paczka przeszla w komplecie" — tak samo jak na sciezce crona.
    import modules.reports.service as serwis_raportow

    monkeypatch.setattr(serwis_raportow, 'get_reports_service',
                        lambda: AtrapaSerwisuBL(orders=[zamowienie()]))

    with app.app_context():
        wynik = serwis_synchronizacji.manual_sync_with_filtering({
            'target_statuses': [138619],
            'force_update': True,
            'auto_status_change': False,
            'recalculate_priorities': False,
        })

        assert 'analityka_ostrzezenie' in wynik
        assert wynik['analityka_ostrzezenie'] is None
        assert SalesOrder.query.count() == 1


def test_wynik_bez_ostrzezenia_gdy_analityka_zapisala_komplet(
        app, serwis_synchronizacji):
    # Kontrola pozytywna: ostrzezenie ma sie pojawiac TYLKO wtedy, gdy
    # naprawde cos przepadlo.
    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie()], sync_type='manual', auto_status_change=False)

        assert wynik['analityka_ostrzezenie'] is None
        assert wynik['analityka']['nowe'] == 1


# ===== awaria bazy JEST awaria, a nie "sukces z zerem pozycji" ==========
#
# ZNALEZISKO WAZNE (trzecia kontrola adwersaryjna).
# `get_active_products_for_prioritization` lapalo KAZDY wyjatek i zwracalo
# pusta liste. `recalculate_all_priorities` widzialo wtedy pusta kolejke
# i konczylo `success: True` z komunikatem "Brak produktow w kolejce
# do priorytetyzacji" - operator dostawal zielony wynik, choc baza nie
# odpowiedziala i priorytety NIE zostaly przeliczone. Kolejka na hali stala
# z nieaktualna numeracja i nikt sie o tym nie dowiadywal.
#
# "Nie ma czego przeliczac" i "nie udalo sie odpytac" to dwa rozne zdania
# i musza dawac dwa rozne wyniki.


class _SesjaKtoraNieOdpowiada:
    """Sesja, ktorej kazde zapytanie konczy sie bledem bazy."""

    def query(self, *_a, **_k):
        from sqlalchemy.exc import OperationalError
        raise OperationalError('SELECT 1', {}, Exception('baza nie odpowiada'))


def test_awaria_pobierania_produktow_nie_udaje_pustej_kolejki(app):
    """Zapytania NIE DA sie wykonac - metoda ma to powiedziec, nie zmilczec.

    Awarie wywoluje prawdziwe zapytanie produkcyjne: sortuje ono przez
    `func.isnull`, ktorego SQLite nie zna (zmierzone: OperationalError
    'near "isnull": syntax error'). To jest dokladnie ten przypadek, ktory
    interesuje nas na produkcji - baza nie odpowiada na zapytanie.
    """
    from modules.production.services.priority_service import (
        NewPriorityCalculator, PriorityError)

    with app.app_context():
        with pytest.raises(PriorityError):
            NewPriorityCalculator().get_active_products_for_prioritization()


def test_awaria_bazy_nie_konczy_przeliczania_sukcesem(app):
    """Ten sam blad widziany z poziomu calego przeliczania."""
    from modules.production.services.priority_service import NewPriorityCalculator

    with app.app_context():
        _kolejka_z_jedna_pozycja()   # w kolejce NAPRAWDE cos jest

        wynik = NewPriorityCalculator().recalculate_all_priorities()

        assert wynik['success'] is False, (
            'awaria bazy zameldowana jako sukces: ' + repr(wynik))
        assert wynik['error']


def test_pusta_kolejka_nadal_jest_sukcesem(app):
    """Kontrola pozytywna: "naprawa" polegajaca na tym, ze KAZDY pusty wynik
    staje sie bledem, ma nie przejsc. Pusta kolejka to poprawny stan."""
    from modules.production.services.priority_service import NewPriorityCalculator

    with app.app_context():
        kalkulator = NewPriorityCalculator()
        kalkulator.get_active_products_for_prioritization = lambda: []

        wynik = kalkulator.recalculate_all_priorities()

        assert wynik['success'] is True
        assert wynik['products_processed'] == 0


def test_awaria_zarezerwowanych_rang_nie_udaje_ich_braku(app):
    """Ta sama dziura, drugie miejsce - i grozniejsze w skutkach.

    `get_reserved_ranks` zwracalo przy awarii PUSTY zbior, czyli zdanie
    "zaden numer nie jest zarezerwowany". `assign_sequential_ranks` rozdawalo
    wtedy numery zajete przez reczne nadpisania operatora
    (`priority_manual_override`) i kolejka na hali dostawala duble - po cichu,
    z wynikiem `success: True`.
    """
    from modules.production.services.priority_service import (
        NewPriorityCalculator, PriorityError)

    with app.app_context():
        kalkulator = NewPriorityCalculator()
        kalkulator._sesja_robocza = lambda: _SesjaKtoraNieOdpowiada()

        with pytest.raises(PriorityError):
            kalkulator.get_reserved_ranks()


# ===== sesja przeliczania nalezy do WATKU, ktory ja zalozyl =============
#
# ZNALEZISKO WAZNE (trzecia kontrola adwersaryjna). Komentarz przy `_sesja`
# twierdzil, ze sesja jest "ustawiana i zerowana WYLACZNIE pod `self._lock`,
# wiec dwa przeliczania nie moga sobie jej podmienic". Twierdzenie bylo
# nieprawdziwe na dwa niezalezne sposoby - oba ponizej.


def test_sesja_przeliczania_nie_wycieka_do_innego_watku(app):
    """ODCZYTY nie braly blokady w ogole.

    `NewPriorityCalculator` jest singletonem procesu
    (`get_priority_calculator`), a gunicorn obsluguje zadania watkami.
    Watek B, wolajacy na tym samym obiekcie publiczne
    `get_active_products_for_prioritization` albo `get_reserved_ranks`
    w trakcie przeliczania w watku A, dostawal PRYWATNA sesje watku A
    i puszczal po niej zapytanie. `Session` SQLAlchemy nie jest bezpieczna
    watkowo, a A zamyka ja w `finally` - B trafial w najlepszym razie
    na `ResourceClosedError`.

    Blokada tego nie lapala, bo jej po prostu nie brano do odczytu.
    """
    import threading
    from modules.production.services.priority_service import NewPriorityCalculator

    with app.app_context():
        produkt = _kolejka_z_jedna_pozycja()

        kalkulator = NewPriorityCalculator()
        kalkulator.get_active_products_for_prioritization = lambda: [produkt]

        weszlismy, pusc = threading.Event(), threading.Event()
        wyniki = {}

        def grupowanie_ktore_czeka(_produkty):
            weszlismy.set()
            pusc.wait(timeout=10)
            return {}

        kalkulator.group_products_by_weeks = grupowanie_ktore_czeka

        def w_tle():
            with app.app_context():
                wyniki['przeliczanie'] = kalkulator.recalculate_all_priorities()

        watek = threading.Thread(target=w_tle)
        watek.start()
        try:
            assert weszlismy.wait(timeout=10), 'watek w tle nie wystartowal'
            # SEDNO: w TYM watku zadne przeliczanie nie trwa, wiec kalkulator
            # ma wskazywac wspoldzielona `db.session`, a nie prywatna sesje
            # watku obok.
            assert kalkulator._sesja_robocza() is db.session, (
                'sesja przeliczania z innego watku wyciekla do tego watku')
        finally:
            pusc.set()
            watek.join(timeout=10)

        assert wyniki['przeliczanie']['success'] is True


def test_zagniezdzone_przeliczanie_nie_podmienia_sesji_zewnetrznemu(app):
    """`self._lock` to RLock, czyli blokada WZNAWIALNA.

    Ten sam watek wchodzi w nia drugi raz bez oporu. Zagniezdzone
    przeliczanie podmienialo wiec sesje zewnetrznemu, a w swoim `finally`
    zerowalo atrybut i ZAMYKALO sesje - zewnetrzne konczylo prace
    na `db.session`, czyli dokladnie tam, skad ja wyprowadzono.
    """
    from modules.production.services.priority_service import NewPriorityCalculator

    with app.app_context():
        produkt = _kolejka_z_jedna_pozycja()

        kalkulator = NewPriorityCalculator()
        kalkulator.get_active_products_for_prioritization = lambda: [produkt]

        slady, glebokosc = {}, []

        def grupowanie_z_zagniezdzeniem(_produkty):
            glebokosc.append(1)
            if len(glebokosc) == 1:
                slady['przed'] = kalkulator._sesja_robocza()
                slady['wewnetrzne'] = kalkulator.recalculate_all_priorities()
                slady['po'] = kalkulator._sesja_robocza()
            return {}

        kalkulator.group_products_by_weeks = grupowanie_z_zagniezdzeniem

        wynik = kalkulator.recalculate_all_priorities()

        assert slady['po'] is slady['przed'], (
            'zagniezdzone przeliczanie podmienilo sesje zewnetrznemu')
        assert slady['wewnetrzne']['success'] is False, (
            'zagniezdzone przeliczanie zostalo wpuszczone')
        assert wynik['success'] is True


# ===== zero w kluczu pozycji zapisuje sie jako BRAK klucza ==============


def test_zerowy_klucz_pozycji_jest_normalizowany_do_nulla(app):
    """ZNALEZISKO WAZNE (trzecia kontrola adwersaryjna).

    `_identyfikator` traktuje 0 i '0' jak brak klucza - ale wiersz zalozony
    PRZED ta regula (albo przez integracje wstawiajaca zera) trzyma w bazie
    doslowne 0 i tak juz zostaje. Dla `_upsert_pozycje` jest bezkluczowy,
    wiec nie dopasuje sie do niczego, a `scripts/uzupelnij_klucze_pozycji.py`
    go NIE WIDZI, bo szuka po `bl_order_product_id IS NULL` - wiersz nie ma
    juz zadnej drogi do odzyskania klucza.

    Grozniejsze jest to, ze zero nie jest NULL-em dla ograniczenia
    UNIQUE(order_id, bl_order_product_id): NULL-e nie koliduja ze soba nigdy,
    ZERA koliduja zawsze (patrz tests/test_sales_models.py). Dwa takie
    wiersze w jednym zamowieniu wywracaja zapis bledem 1062.

    Dlatego przy zapisie zero jest NORMALIZOWANE do NULL-a: to ta sama tresc
    zapisana kanonicznie.
    """
    from modules.reports.ingest import zapisz_zamowienia

    with app.app_context():
        zam = SalesOrder(baselinker_order_id=50854536, date_created=date(2026, 9, 18))
        zam.items = [SalesOrderItem(bl_order_product_id=0, quantity=1,
                                    raw_product_name=BLAT)]
        db.session.add(zam)
        db.session.commit()
        id_wiersza = zam.items[0].id

        zapisz_zamowienia([zamowienie()], zrodlo='produkcja')
        db.session.expire_all()

        wiersz = db.session.query(SalesOrderItem).get(id_wiersza)
        assert wiersz is not None, 'wiersz z zerem zostal skasowany'
        assert wiersz.bl_order_product_id is None, (
            'zero zostalo w bazie: %r' % wiersz.bl_order_product_id)
