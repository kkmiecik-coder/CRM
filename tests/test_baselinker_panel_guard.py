# -*- coding: utf-8 -*-
"""
Panel handlowca na wycenie, która ma już zamówienie.

Ścieżka panelu (POST /baselinker/api/quote/<id>/create-order) nie sprawdzała
`base_linker_order_id`. Na wycenie zamówionej przez klienta drugie kliknięcie
tworzyło DRUGIE realne zamówienie, nadpisywało numer i — nowość tej gałęzi —
`baselinker_order_page`, czyli link, który klient JUŻ DOSTAŁ. Link zaczynał
wskazywać zamówienie, o którym klient nic nie wie, a pierwsze zostawało
osierocone.

BaselinkerService jest atrapą — żaden test nie dotyka BaseLinkera.
"""
import os
import sys
from datetime import datetime

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db  # noqa: E402
from modules.baselinker import baselinker_bp  # noqa: E402
from modules.baselinker import routers as bl_routers  # noqa: E402
from modules.baselinker.models import (  # noqa: E402
    BaselinkerConfig, BaselinkerOrderLog, STATUS_PROBA_NIEPEWNA,
)
from modules.calculator.models import (  # noqa: E402
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: E402
from modules.quotes.models import QuoteStatus  # noqa: E402
from modules.quotes.services import checkout_service  # noqa: E402
from modules.users.models import User  # noqa: E402

ZRODLO = 85727
EMAIL_HANDLOWCA = 'handlowiec@woodpower.pl'
EMAIL_ADMINA = 'admin@woodpower.pl'

_TABELE = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    BaselinkerConfig, BaselinkerOrderLog,
)]


@pytest.fixture()
def aplikacja(monkeypatch):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(baselinker_bp, url_prefix='/baselinker')
    db.init_app(app)

    # Uprawnienia sprawdza PermissionService (osobny moduł, własne testy) —
    # tutaj interesuje nas wyłącznie guard na już zamówionej wycenie.
    from modules.users.services.permission_service import PermissionService
    monkeypatch.setattr(PermissionService, 'user_has_module_access',
                        staticmethod(lambda user_id, module_key: True))

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABELE)
        yield app
        db.session.remove()


@pytest.fixture()
def klient_http(aplikacja):
    klient = aplikacja.test_client()
    with klient.session_transaction() as sesja:
        sesja['user_email'] = EMAIL_HANDLOWCA
    return klient


@pytest.fixture()
def klient_http_admin(aplikacja):
    klient = aplikacja.test_client()
    with klient.session_transaction() as sesja:
        sesja['user_email'] = EMAIL_ADMINA
    return klient


@pytest.fixture()
def serwis(monkeypatch):
    """Atrapa BaselinkerService podstawiona w checkout_service.

    Podstawiamy ją TAM, a nie w routerze panelu, bo panel nie woła już serwisu
    sam: obie ścieżki — publiczny checkout klienta i panel handlowca —
    przechodzą przez jeden zabezpieczony tor (checkout_service.zloz_zamowienie).
    Dopóki panel miał własną, słabszą kopię guardu, przegrywał wyścig
    z checkoutem klienta i dawał dwa realne zamówienia.
    """
    wywolania = []

    class _Atrapa:
        def __init__(self, *a, **k):
            pass

        def create_order_from_quote(self, quote, user_id, config):
            wywolania.append(config)
            quote.base_linker_order_id = '888'
            quote.baselinker_order_page = 'https://blsklep.pl/z/888'
            quote.order_attempt_started_at = None   # jak realny serwis
            db.session.commit()
            return {'success': True, 'order_id': 888}

    monkeypatch.setattr(checkout_service, 'BaselinkerService', _Atrapa)
    return wywolania


def _zasiej(base_linker_order_id=None, order_page=None):
    db.session.add(QuoteStatus(id=4, name='Złożone'))
    db.session.add(BaselinkerConfig(
        config_type='order_source', baselinker_id=ZRODLO, name='Dębuś VPS',
        is_default=False, is_active=True, sort_order=100,
        created_at=datetime(2026, 8, 30), updated_at=datetime(2026, 8, 30)))
    db.session.add(User(email=EMAIL_HANDLOWCA, first_name='Han', last_name='Dlowiec',
                        role='user', password='x', active=True))
    db.session.add(User(email=EMAIL_ADMINA, first_name='Ad', last_name='Min',
                        role='admin', password='x', active=True))
    klient = Client(client_number='K-1', client_name='Jan Testowy',
                    email='jan@example.pl', phone='601234567')
    db.session.add(klient)
    db.session.flush()
    wycena = Quote(quote_number='420/08/26/W',
                   public_token='TOKENPANEL0000000000000000001',
                   status_id=3, client_id=klient.id, quote_type='brutto',
                   courier_name='DPD', shipping_cost_brutto=123.0,
                   base_linker_order_id=base_linker_order_id,
                   baselinker_order_page=order_page)
    db.session.add(wycena)
    db.session.flush()
    db.session.add(QuoteItem(
        quote_id=wycena.id, product_index=1, variant_code='dab-lity-ab',
        length_cm=100, width_cm=50, thickness_cm=3,
        price_netto=100.0, price_brutto=123.0, is_selected=True))
    db.session.commit()
    return wycena.id


def _config():
    return {'order_source_id': ZRODLO, 'payment_method': 'Przelew bankowy',
            'delivery_method': 'DPD', 'shipping_cost_override': 123.0}


class TestPanelNaWycenieZamowionej:
    def test_panel_nie_tworzy_drugiego_zamowienia(self, aplikacja, klient_http, serwis):
        id_wyceny = _zasiej(base_linker_order_id='501',
                            order_page='https://blsklep.pl/z/501')

        odpowiedz = klient_http.post(
            '/baselinker/api/quote/%d/create-order' % id_wyceny, json=_config())

        assert odpowiedz.status_code == 409
        assert serwis == [], 'drugie realne zamówienie w BaseLinkerze'

    def test_panel_nie_nadpisuje_linku_klienta(self, aplikacja, klient_http, serwis):
        id_wyceny = _zasiej(base_linker_order_id='501',
                            order_page='https://blsklep.pl/z/501')

        klient_http.post('/baselinker/api/quote/%d/create-order' % id_wyceny,
                         json=_config())

        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            assert wycena.base_linker_order_id == '501'
            assert wycena.baselinker_order_page == 'https://blsklep.pl/z/501'

    def test_odmowa_niesie_numer_istniejacego_zamowienia(self, aplikacja, klient_http,
                                                         serwis):
        # Handlowiec ma z komunikatu wiedzieć, że zamówienie już jest i które.
        id_wyceny = _zasiej(base_linker_order_id='501')

        body = klient_http.post('/baselinker/api/quote/%d/create-order' % id_wyceny,
                                json=_config()).get_json()

        assert body['success'] is False
        # Numer przychodzi znormalizowany do liczby — tak samo jak w ścieżce
        # klienta, bo obie idą przez ten sam tor. Kolumna jest tekstowa, więc
        # gdy siedzi w niej coś nieliczbowego, wraca bez zmian.
        assert body['order_id'] == 501
        assert '501' in body['error']

    def test_wycena_bez_zamowienia_dalej_daje_sie_zamowic(self, aplikacja, klient_http,
                                                          serwis):
        # Kontrola negatywna: guard nie może zablokować normalnej pracy panelu.
        id_wyceny = _zasiej()

        odpowiedz = klient_http.post(
            '/baselinker/api/quote/%d/create-order' % id_wyceny, json=_config())

        assert odpowiedz.status_code == 200
        assert odpowiedz.get_json()['success'] is True
        assert len(serwis) == 1

class TestPanelANierozstrzygnietaProbaKlienta:
    """N3: wyścig checkout klienta ↔ panel handlowca, w obie strony.

    Guard panelu czytał `base_linker_order_id` bez blokady i PRZED addOrder,
    a checkout klienta zapisuje ten numer dopiero po powrocie z BaseLinkera.
    Okno było wielkości całego wywołania HTTP (do 30 s) i dawało DWA realne
    zamówienia (sondy W3/W3b recenzji). Dziś obie ścieżki wchodzą przez tę samą
    blokadę i ten sam znacznik próby.
    """

    def test_panel_nie_zamawia_gdy_klient_ma_probe_w_toku(self, aplikacja,
                                                          klient_http, serwis):
        id_wyceny = _zasiej()
        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            wycena.order_attempt_started_at = datetime.utcnow()
            db.session.commit()

        odpowiedz = klient_http.post(
            '/baselinker/api/quote/%d/create-order' % id_wyceny, json=_config())

        assert odpowiedz.status_code == 409
        assert serwis == [], 'DRUGIE realne zamówienie w BaseLinkerze'
        assert 'BaseLinker' in odpowiedz.get_json()['error']

    def test_panel_nie_zamawia_po_nierozstrzygnietej_probie(self, aplikacja,
                                                            klient_http, serwis):
        id_wyceny = _zasiej()
        with aplikacja.app_context():
            db.session.add(BaselinkerOrderLog(
                quote_id=id_wyceny, action='create_order',
                status=STATUS_PROBA_NIEPEWNA))
            db.session.commit()

        odpowiedz = klient_http.post(
            '/baselinker/api/quote/%d/create-order' % id_wyceny, json=_config())

        assert odpowiedz.status_code == 409
        assert serwis == []

    def test_panel_zostawia_wlasny_znacznik_przed_wywolaniem(self, aplikacja,
                                                             klient_http,
                                                             monkeypatch):
        # Druga strona tego samego wyścigu: gdy zamawia panel, checkout klienta
        # musi mieć co zobaczyć. Rollback w atrapie kasuje wszystko, co było
        # tylko we flushu — znacznik, który go przeżył, był zacommitowany.
        widziane = {}

        class _Atrapa:
            def __init__(self, *a, **k):
                pass

            def create_order_from_quote(self, quote, user_id, config):
                db.session.rollback()
                widziane['znacznik'] = Quote.query.get(
                    quote.id).order_attempt_started_at
                return {'success': True, 'order_id': 888}

        monkeypatch.setattr(checkout_service, 'BaselinkerService', _Atrapa)
        id_wyceny = _zasiej()

        klient_http.post('/baselinker/api/quote/%d/create-order' % id_wyceny,
                         json=_config())

        assert widziane['znacznik'] is not None


class TestPanelPoUdanymAddOrderZPadnietymZapisem:
    """N4: handlowiec też ma dostać prawdę z punktu bez powrotu.

    Naprawa U1 dowiozła ją klientowi, ale nie handlowcowi: router czytał
    wyłącznie `success` i `error`, więc przy błędzie bazy PO udanym addOrder
    handlowiec widział surowy komunikat MySQL-a i miał pełne prawo kliknąć
    drugi raz (sondy P1/P2 recenzji).
    """

    def _atrapa(self, monkeypatch, wywolania):
        class _Atrapa:
            def __init__(self, *a, **k):
                pass

            def create_order_from_quote(self, quote, user_id, config):
                wywolania.append(config)
                return {'success': False,
                        'error': 'Lost connection to MySQL server during query',
                        'zamowienie_utworzone': True, 'niepewne': False,
                        'order_id': 900}

        monkeypatch.setattr(checkout_service, 'BaselinkerService', _Atrapa)

    def test_handlowiec_nie_widzi_surowego_bledu_bazy(self, aplikacja,
                                                      klient_http, monkeypatch):
        self._atrapa(monkeypatch, [])
        id_wyceny = _zasiej()

        odpowiedz = klient_http.post(
            '/baselinker/api/quote/%d/create-order' % id_wyceny, json=_config())
        body = odpowiedz.get_json()

        assert body['success'] is False
        assert body['zamowienie_utworzone'] is True
        assert body['order_id'] == 900
        assert 'Lost connection' not in body['error']
        assert 'nie składaj' in body['error'].lower()
        assert '900' in body['error']

    def test_drugie_kliknieci_nie_tworzy_drugiego_zamowienia(self, aplikacja,
                                                             klient_http,
                                                             monkeypatch):
        wywolania = []
        self._atrapa(monkeypatch, wywolania)
        id_wyceny = _zasiej()

        klient_http.post('/baselinker/api/quote/%d/create-order' % id_wyceny,
                         json=_config())
        druga = klient_http.post('/baselinker/api/quote/%d/create-order' % id_wyceny,
                                 json=_config())

        assert druga.status_code == 409
        assert len(wywolania) == 1, 'DRUGIE realne zamówienie w BaseLinkerze'

    def test_niepewna_proba_tez_nie_zaprasza_do_powtorki(self, aplikacja,
                                                         klient_http, monkeypatch):
        class _Atrapa:
            def __init__(self, *a, **k):
                pass

            def create_order_from_quote(self, quote, user_id, config):
                return {'success': False, 'error': 'ReadTimeout', 'niepewne': True,
                        'zamowienie_utworzone': False, 'order_id': None}

        monkeypatch.setattr(checkout_service, 'BaselinkerService', _Atrapa)
        id_wyceny = _zasiej()

        body = klient_http.post(
            '/baselinker/api/quote/%d/create-order' % id_wyceny,
            json=_config()).get_json()

        assert body['success'] is False
        assert body['niepewne'] is True
        assert 'nie wiemy' in body['error'].lower()


class TestOdpiecieZamowienia:
    """N9: droga wyjścia z odmowy 409 dla uprawnionego człowieka.

    W całym modules/ nic nie kasowało base_linker_order_id: zamówienie
    anulowane w BaseLinkerze albo złożone pomyłkowo zamykało wycenę na zawsze,
    a jedynym ratunkiem był ręczny UPDATE w bazie.
    """

    def test_admin_odpina_zamowienie_i_wycena_znow_da_sie_zamowic(
            self, aplikacja, klient_http_admin, serwis):
        id_wyceny = _zasiej(base_linker_order_id='501',
                            order_page='https://blsklep.pl/z/501')

        odpowiedz = klient_http_admin.post(
            '/baselinker/api/quote/%d/detach-order' % id_wyceny)

        assert odpowiedz.status_code == 200
        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            assert wycena.base_linker_order_id is None
            assert wycena.baselinker_order_page is None

        ponowne = klient_http_admin.post(
            '/baselinker/api/quote/%d/create-order' % id_wyceny, json=_config())
        assert ponowne.status_code == 200
        assert len(serwis) == 1

    def test_odpiecie_zdejmuje_takze_znacznik_nierozstrzygnietej_proby(
            self, aplikacja, klient_http_admin, serwis):
        id_wyceny = _zasiej()
        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            wycena.order_attempt_started_at = datetime.utcnow()
            db.session.add(BaselinkerOrderLog(
                quote_id=id_wyceny, action='create_order',
                status=STATUS_PROBA_NIEPEWNA))
            db.session.commit()

        odpowiedz = klient_http_admin.post(
            '/baselinker/api/quote/%d/detach-order' % id_wyceny)

        assert odpowiedz.status_code == 200
        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            assert wycena.order_attempt_started_at is None
            assert checkout_service.wisi_nierozstrzygnieta_proba(wycena) is False

    def test_odpiecie_zostawia_slad_w_logu(self, aplikacja, klient_http_admin,
                                           serwis):
        id_wyceny = _zasiej(base_linker_order_id='501')

        klient_http_admin.post('/baselinker/api/quote/%d/detach-order' % id_wyceny)

        with aplikacja.app_context():
            wpis = BaselinkerOrderLog.query.filter_by(
                quote_id=id_wyceny, action='detach_order').first()
            assert wpis is not None
            assert wpis.baselinker_order_id == 501

    def test_zwykly_handlowiec_nie_odpina(self, aplikacja, klient_http, serwis):
        # Odpięcie kasuje jedyny ślad wiążący wycenę z realnym zamówieniem —
        # to decyzja administratora, nie codzienna akcja panelu.
        id_wyceny = _zasiej(base_linker_order_id='501')

        odpowiedz = klient_http.post(
            '/baselinker/api/quote/%d/detach-order' % id_wyceny)

        assert odpowiedz.status_code == 403
        with aplikacja.app_context():
            assert Quote.query.get(id_wyceny).base_linker_order_id == '501'

    def test_niezalogowany_nie_odpina(self, aplikacja, serwis):
        # Kontrola negatywna: droga wyjścia jest dla CZŁOWIEKA z uprawnieniami,
        # nie dla klienta ze strony wyceny.
        id_wyceny = _zasiej(base_linker_order_id='501')

        odpowiedz = aplikacja.test_client().post(
            '/baselinker/api/quote/%d/detach-order' % id_wyceny)

        assert odpowiedz.status_code in (401, 302)
        with aplikacja.app_context():
            assert Quote.query.get(id_wyceny).base_linker_order_id == '501'


class TestOdpiecieWTrakcieTrwajacejProby:
    """N-B: odpięcie w oknie tuż po zapisie znacznika dawało DWA zamówienia.

    Sonda B recenzji: znacznik jest już zacommitowany, ale wywołanie
    BaseLinkera nie zdążyło jeszcze założyć blokady wiersza (przez klucz obcy
    z wpisu w logu). Odpięcie trafiające w to okno kasowało znacznik, drugi
    klient przechodził guard i powstawało drugie REALNE zamówienie. Odpięcie
    ma tu odmówić — sprawy nie da się rozstrzygnąć, dopóki pierwsza próba
    wisi w BaseLinkerze.
    """

    def test_odpiecie_w_trakcie_proby_odmawia_i_zostawia_znacznik(
            self, aplikacja, klient_http_admin, serwis):
        id_wyceny = _zasiej()
        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            wycena.order_attempt_started_at = datetime.utcnow()
            db.session.commit()

        odpowiedz = klient_http_admin.post(
            '/baselinker/api/quote/%d/detach-order' % id_wyceny)

        assert odpowiedz.status_code == 409
        assert odpowiedz.get_json()['success'] is False
        with aplikacja.app_context():
            assert Quote.query.get(id_wyceny).order_attempt_started_at is not None

    def test_po_odmowie_wycena_dalej_jest_zablokowana_dla_klienta(
            self, aplikacja, klient_http_admin, serwis):
        # Sedno sondy B: gdyby odpięcie przeszło, kolejne żądanie utworzyłoby
        # drugie realne zamówienie.
        id_wyceny = _zasiej()
        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            wycena.order_attempt_started_at = datetime.utcnow()
            db.session.commit()

        klient_http_admin.post('/baselinker/api/quote/%d/detach-order' % id_wyceny)
        ponowne = klient_http_admin.post(
            '/baselinker/api/quote/%d/create-order' % id_wyceny, json=_config())

        assert ponowne.status_code == 409
        assert serwis == [], 'DRUGIE realne zamówienie w BaseLinkerze'
