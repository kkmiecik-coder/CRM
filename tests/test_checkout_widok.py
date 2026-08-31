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
from modules.baselinker.models import BaselinkerConfig  # noqa: E402
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
    BaselinkerConfig,
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
            order_page=None, wybrana_pozycja=True, email='jan@example.pl'):
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
