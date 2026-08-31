# -*- coding: utf-8 -*-
"""
Strona wyceny widziana przez klienta — stany przycisku zamawiania.

Do tej pory strona miała jeden przełącznik: `is_accepted`. Klient, który
wycenę zaakceptował, dostawał wyłącznie zablokowany przycisk „Wycena
zaakceptowana" i nie miał czym zamówić — na tym utknął właściciel.

Stany, które strona musi rozróżniać:
  1. można zamówić            → aktywny przycisk „Zamów",
  2. zamówienie już złożone   → link do strony zamówienia, bez „Zamów",
  3. nie da się zamówić       → czytelny powód, a NIE martwy przycisk.

Renderujemy realny szablon na minimalnym Flasku (SQLite in-memory) —
konwencja tests/test_checkout_endpoint.py. Żaden test nie dotyka BaseLinkera.
"""
import os
import sys
from datetime import datetime

import pytest
from flask import Flask
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db  # noqa: E402
from modules.baselinker.models import BaselinkerConfig, BaselinkerOrderLog  # noqa: E402
from modules.quotes.services.checkout_service import STATUS_PROBA_NIEPEWNA  # noqa: E402
from modules.calculator.models import (  # noqa: E402
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: E402
from modules.preview3d_ar import preview3d_ar_bp  # noqa: E402
from modules.quotes import quotes_bp  # noqa: E402
from modules.quotes.models import QuoteStatus  # noqa: E402
from modules.users.models import User  # noqa: E402

TOKEN = 'TOKENWIDOK0000000000000000001'
KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_TABELE = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    BaselinkerConfig, BaselinkerOrderLog,
)]


@pytest.fixture()
def aplikacja():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    # Szablon wołany jest po ścieżce "quotes/templates/..." — tak jak w app.py,
    # gdzie katalog modules/ jest doklejony do loadera Jinjy.
    app.jinja_loader = ChoiceLoader([
        app.jinja_loader,
        FileSystemLoader(os.path.join(KORZEN, 'modules')),
    ])
    app.register_blueprint(quotes_bp, url_prefix='/quotes')
    # Szablon buduje url_for('preview3d_ar.static', ...) — bez tego blueprintu
    # render wywala się na BuildError i widok oddaje stronę błędu.
    app.register_blueprint(preview3d_ar_bp)
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABELE)
        yield app
        db.session.remove()


@pytest.fixture()
def klient_http(aplikacja):
    return aplikacja.test_client()


def _zasiej(status_id=1, is_client_editable=True, order_id=None,
            order_page=None, wybrana_pozycja=True, email='jan@example.pl',
            niepewna_proba=False):
    db.session.add(QuoteStatus(id=3, name='Zaakceptowane'))
    db.session.add(QuoteStatus(id=4, name='Złożone'))
    klient = Client(client_number='K-1', client_name='Jan Testowy',
                    email=email, phone='601234567')
    db.session.add(klient)
    db.session.flush()
    wycena = Quote(quote_number='410/08/26/W', public_token=TOKEN,
                   status_id=status_id, client_id=klient.id, quote_type='brutto',
                   courier_name='DPD', shipping_cost_brutto=123.0,
                   is_client_editable=is_client_editable,
                   base_linker_order_id=order_id,
                   baselinker_order_page=order_page,
                   created_at=datetime(2026, 8, 30))
    if status_id in (3, 4):
        wycena.acceptance_date = datetime(2026, 8, 30, 12, 0, 0)
    db.session.add(wycena)
    db.session.flush()
    db.session.add(QuoteItem(
        quote_id=wycena.id, product_index=1, variant_code='dab-lity-ab',
        length_cm=100, width_cm=50, thickness_cm=3,
        price_netto=100.0, price_brutto=123.0, is_selected=wybrana_pozycja))
    if niepewna_proba:
        # Ślad po próbie, po której nie wiemy, czy zamówienie powstało.
        db.session.add(BaselinkerOrderLog(
            quote_id=wycena.id, action='create_order',
            status=STATUS_PROBA_NIEPEWNA, created_at=datetime(2026, 8, 30, 13, 0)))
    db.session.commit()
    return wycena.id


def _strona(klient_http):
    odpowiedz = klient_http.get(f'/quotes/c/{TOKEN}')
    assert odpowiedz.status_code == 200
    return odpowiedz.get_data(as_text=True)


class TestPrzyciskZamawiania:
    def test_swieza_wycena_ma_przycisk_zamow(self, aplikacja, klient_http):
        # Decyzja właściciela: „Zamów" dla WSZYSTKICH wycen, bez rozróżniania
        # na wystawione przez bota i przez handlowca.
        _zasiej()

        html = _strona(klient_http)

        assert 'Zamów' in html
        assert 'Akceptuj wycenę' not in html

    def test_zaakceptowana_wycena_bez_zamowienia_nadal_ma_przycisk_zamow(
            self, aplikacja, klient_http):
        # Dokładnie stan, na którym utknął właściciel: wycena zaakceptowana,
        # zamówienia brak, a jedyny przycisk był zablokowany.
        _zasiej(status_id=3, is_client_editable=False)

        html = _strona(klient_http)

        assert 'Zamów' in html
        assert 'Wycena zaakceptowana' not in html

    def test_zlozone_zamowienie_pokazuje_link_zamiast_przycisku(
            self, aplikacja, klient_http):
        _zasiej(status_id=4, is_client_editable=False, order_id='501',
                order_page='https://blsklep.pl/z/501')

        html = _strona(klient_http)

        assert 'https://blsklep.pl/z/501' in html
        assert 'Zamówienie zostało złożone' in html
        assert '>Zamów<' not in html

    def test_zlozone_zamowienie_bez_linku_nie_pokazuje_martwego_odnosnika(
            self, aplikacja, klient_http):
        # BaseLinker nie zawsze oddaje order_page — brak linku nie może
        # zamienić się w odnośnik prowadzący donikąd.
        _zasiej(status_id=4, is_client_editable=False, order_id='501')

        html = _strona(klient_http)

        assert 'Zamówienie zostało złożone' in html
        assert 'href=""' not in html
        assert '>Zamów<' not in html

    def test_wycena_niekwalifikujaca_sie_tlumaczy_powod_zamiast_martwego_przycisku(
            self, aplikacja, klient_http):
        # Zaakceptowana, bez zamówienia, ale żadna pozycja nie jest wybrana —
        # endpoint odbiłby ją z 400. Klient ma zobaczyć powód, nie przycisk.
        _zasiej(status_id=3, is_client_editable=False, wybrana_pozycja=False)

        html = _strona(klient_http)

        assert '>Zamów<' not in html
        assert 'skontaktuj się z nami' in html.lower()


class TestBialaListaSchematowLinku:
    """Szablon wstawiał `link_zamowienia` do href bez sprawdzenia schematu.

    Wartość pochodzi z odpowiedzi BaseLinkera, więc ryzyko jest niskie — ale
    JavaScript ma tę białą listę od początku (bezpiecznyLinkZamowienia),
    a szablon obsługuje ścieżkę CZĘSTSZĄ: każde wejście na zamówioną wycenę.
    """

    def test_link_http_przechodzi(self, aplikacja, klient_http):
        _zasiej(status_id=4, is_client_editable=False, order_id='501',
                order_page='https://blsklep.pl/z/501')

        assert 'https://blsklep.pl/z/501' in _strona(klient_http)

    def test_schemat_javascript_nie_trafia_do_href(self, aplikacja, klient_http):
        _zasiej(status_id=4, is_client_editable=False, order_id='501',
                order_page='javascript:alert(1)')

        html = _strona(klient_http)

        assert 'javascript:alert' not in html
        # Brak linku nie może zamienić się w odnośnik prowadzący donikąd —
        # klient dostaje ten sam stan co przy braku order_page.
        assert 'Zamówienie zostało złożone' in html
        assert 'href=""' not in html

    def test_schemat_data_nie_trafia_do_href(self, aplikacja, klient_http):
        _zasiej(status_id=4, is_client_editable=False, order_id='501',
                order_page='data:text/html,<script>alert(1)</script>')

        assert 'data:text/html' not in _strona(klient_http)


class TestNierozstrzygnietaProbaZamowienia:
    """Timeout BaseLinkera + odświeżenie strony = drugie realne zamówienie.

    Po utracie łączności numer zamówienia nie zapisuje się na wycenie, więc
    guard idempotencji nie ma czego znaleźć. Jedyną obroną był JavaScript
    (wygaszony przycisk w modalu), a F5 omijało ją w całości — klient po
    komunikacie „nie wiemy" odruchowo odświeża stronę.
    """

    def test_po_nierozstrzygnietej_probie_nie_ma_przycisku_zamow(
            self, aplikacja, klient_http):
        _zasiej(status_id=3, is_client_editable=False, niepewna_proba=True)

        html = _strona(klient_http)

        assert '>Zamów<' not in html
        assert 'window.MOZNA_ZAMOWIC = false' in html

    def test_klient_dostaje_powod_a_nie_sam_brak_przycisku(self, aplikacja,
                                                           klient_http):
        _zasiej(status_id=3, is_client_editable=False, niepewna_proba=True)

        html = _strona(klient_http)

        assert 'Sprawdzamy' in html
        assert 'nie składaj' in html.lower()
        assert '410/08/26/W' in html

    def test_wycena_bez_nierozstrzygnietej_proby_ma_przycisk(self, aplikacja,
                                                             klient_http):
        # Kontrola negatywna: blokada nie może zapalać się bez powodu.
        _zasiej(status_id=3, is_client_editable=False)

        assert '>Zamów<' in _strona(klient_http)


class TestFlagaDlaSkryptuStrony:
    """client_quote.js sam blokuje przyciski po wczytaniu danych z API.

    Dopóki robił to na podstawie `is_client_editable`, gasił „Zamów" na wycenie
    zaakceptowanej — czyli dokładnie tam, gdzie przycisk ma działać. Szablon
    musi mu podać osobną flagę.
    """

    def test_zaakceptowana_wycena_bez_zamowienia_ma_flage_wlaczona(
            self, aplikacja, klient_http):
        _zasiej(status_id=3, is_client_editable=False)

        assert 'window.MOZNA_ZAMOWIC = true' in _strona(klient_http)

    def test_wycena_z_zamowieniem_ma_flage_wylaczona(self, aplikacja, klient_http):
        _zasiej(status_id=4, is_client_editable=False, order_id='501',
                order_page='https://blsklep.pl/z/501')

        assert 'window.MOZNA_ZAMOWIC = false' in _strona(klient_http)


class TestZnacznikProbyNaWierszuWyceny:
    """Strona musi widzieć znacznik z wiersza wyceny, nie tylko wpis w logu.

    Wpis w logu powstaje w obsłudze wyjątku — a gdy niesprawna jest baza, nie
    powstaje wcale (sonda D3b recenzji). Znacznik na wycenie jest zapisany
    PRZED wywołaniem BaseLinkera, więc to on rozstrzyga, czy klientowi wolno
    pokazać przycisk.
    """

    def test_swiezy_znacznik_bez_wpisu_w_logu_gasi_przycisk(self, aplikacja,
                                                            klient_http):
        id_wyceny = _zasiej(status_id=3, is_client_editable=False)
        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            wycena.order_attempt_started_at = datetime.utcnow()
            db.session.commit()

        html = _strona(klient_http)

        assert 'id="acceptQuoteBtnDesktop"' not in html
        assert 'nie składaj go ponownie' in html.lower()

    def test_zamowiona_wycena_ze_znacznikiem_pokazuje_zamowienie(self, aplikacja,
                                                                  klient_http):
        # Kontrola negatywna: gdy zamówienie JEST, znacznik nie ma prawa
        # zamienić potwierdzenia w komunikat o niepewności.
        id_wyceny = _zasiej(status_id=4, is_client_editable=False, order_id='501',
                            order_page='https://blsklep.pl/z/501')
        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            wycena.order_attempt_started_at = datetime.utcnow()
            db.session.commit()

        html = _strona(klient_http)

        assert 'Zamówienie zostało złożone' in html
        assert 'nie składaj go ponownie' not in html.lower()


class TestDaneDostawyDlaModala:
    """N-C: modal musi wiedzieć, czy TA wycena jedzie kurierem.

    Dopóki wstępne zaznaczenie „odbioru osobistego" opierało się wyłącznie na
    współdzielonym rekordzie klienta, wycena kurierska takiego klienta jechała
    do BaseLinkera z zerowym kosztem dostawy. Dane dostawy wyceny wstrzykuje
    szablon — modal nie ma innego źródła.
    """

    def test_strona_podaje_kuriera_i_koszt_dostawy(self, aplikacja, klient_http):
        _zasiej(status_id=3, is_client_editable=False)

        html = _strona(klient_http)

        assert 'courier_name' in html
        assert '"DPD"' in html
        assert 'koszt_dostawy' in html
        assert '123.0' in html

    def test_wycena_bez_kuriera_nie_udaje_kurierskiej(self, aplikacja,
                                                      klient_http):
        id_wyceny = _zasiej(status_id=3, is_client_editable=False)
        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            wycena.courier_name = None
            wycena.shipping_cost_brutto = 0
            db.session.commit()

        html = _strona(klient_http)

        assert 'courier_name: ""' in html
        assert 'koszt_dostawy: 0.0' in html
