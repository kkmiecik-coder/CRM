# -*- coding: utf-8 -*-
"""
Trwały znacznik próby zamówienia — zapisany PRZED wywołaniem BaseLinkera.

Poprzednia runda poprawek zostawiła jedną wspólną przyczynę czterech dróg do
drugiego realnego zamówienia: JEDYNY trwały ślad próby powstawał PO awarii —
w obsłudze wyjątku, w zapisie awaryjnym numeru, we wpisie `uncertain`. Czyli
dokładnie wtedy, gdy niesprawna bywała właśnie baza. Gdy padł też ten zapis,
do bazy nie trafiało NIC i odświeżenie strony przywracało klientowi przycisk.

Te testy przypinają odwrotną kolejność: znacznik jest w bazie ZANIM
poleci `addOrder`, przeżywa awarię wszystkiego, co dzieje się później,
i zdejmuje się dopiero po rozstrzygnięciu.

BaselinkerService jest zawsze atrapą — żaden test nie dotyka BaseLinkera.
"""
import os
import sys
from datetime import datetime, timedelta

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db  # noqa: E402
from modules.baselinker.models import (  # noqa: E402
    BaselinkerOrderLog, STATUS_PROBA_NIEPEWNA,
)
from modules.calculator.models import (  # noqa: E402
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: E402
from modules.quotes.models import QuoteStatus  # noqa: E402
from modules.quotes.services import checkout_service  # noqa: E402
from modules.users.models import User  # noqa: E402

_TABELE = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    BaselinkerOrderLog,
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
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABELE)
        yield app
        db.session.remove()


def _zasiej(numer='430/08/26/W', token='TOKENZNACZNIK0000000000000001'):
    klient = Client(client_number='K-%s' % numer, client_name='Jan Testowy',
                    email='jan@example.pl', phone='601234567')
    db.session.add(klient)
    db.session.flush()
    wycena = Quote(quote_number=numer, public_token=token, status_id=3,
                   client_id=klient.id, quote_type='brutto', courier_name='DPD')
    db.session.add(wycena)
    db.session.flush()
    db.session.add(QuoteItem(
        quote_id=wycena.id, product_index=1, variant_code='dab-lity-ab',
        length_cm=100, width_cm=50, thickness_cm=3,
        price_netto=100.0, price_brutto=123.0, is_selected=True))
    db.session.commit()
    return wycena


def _atrapa(monkeypatch, zachowanie):
    """Atrapa serwisu: `zachowanie(quote, licznik)` zwraca wynik create_order_from_quote."""
    wywolania = []

    class _Atrapa:
        def __init__(self, *a, **k):
            pass

        def create_order_from_quote(self, quote, user_id, config):
            wywolania.append(config)
            return zachowanie(quote, len(wywolania))

    monkeypatch.setattr(checkout_service, 'BaselinkerService', _Atrapa)
    return wywolania


def _zamow(wycena):
    return checkout_service.zloz_zamowienie_klienta(
        wycena, order_source_id=85727, bot_user_id=None)


class TestZnacznikPrzedWywolaniem:
    """Znacznik ma być TRWAŁY już w chwili strzału do BaseLinkera."""

    def test_znacznik_jest_zacommitowany_zanim_poleci_addorder(
            self, aplikacja, monkeypatch):
        # Sedno przyczyny źródłowej. Rollback wewnątrz atrapy kasuje wszystko,
        # co było tylko we flushu — jeśli po nim znacznik dalej jest na wycenie,
        # to znaczy, że został ZACOMMITOWANY przed wywołaniem BaseLinkera.
        widziane = {}

        def zachowanie(quote, _licznik):
            db.session.rollback()
            odswiezona = Quote.query.get(quote.id)
            widziane['znacznik'] = odswiezona.order_attempt_started_at
            return {'success': True, 'order_id': 900}

        _atrapa(monkeypatch, zachowanie)
        wycena = _zasiej()

        _zamow(wycena)

        assert widziane['znacznik'] is not None, \
            'znacznik próby nie przeżył rollbacku — nie był zacommitowany'

    def test_po_sukcesie_znacznik_jest_zdjety(self, aplikacja, monkeypatch):
        # Kontrola negatywna: znacznik nie może zostać po udanym zamówieniu,
        # bo to on blokuje kolejne próby.
        def zachowanie(quote, _licznik):
            quote.base_linker_order_id = '900'
            quote.order_attempt_started_at = None   # jak realny serwis: jeden commit
            db.session.commit()
            return {'success': True, 'order_id': 900}

        _atrapa(monkeypatch, zachowanie)
        wycena = _zasiej()

        wynik = _zamow(wycena)

        assert wynik['ok'] is True
        assert Quote.query.get(wycena.id).order_attempt_started_at is None

    def test_po_odmowie_baselinkera_znacznik_jest_zdjety(self, aplikacja, monkeypatch):
        # API odpowiedziało i odmówiło — zamówienia NA PEWNO nie ma, powtórka
        # musi być możliwa.
        wywolania = _atrapa(monkeypatch, lambda q, n: {
            'success': False, 'error': 'Brak tokenu API',
            'niepewne': False, 'zamowienie_utworzone': False})
        wycena = _zasiej()

        pierwszy = _zamow(wycena)

        assert pierwszy['ok'] is False
        assert Quote.query.get(wycena.id).order_attempt_started_at is None
        assert len(wywolania) == 1


class TestPadnietyZapisAwaryjny:
    """Sonda D4 recenzenta: udany addOrder, pada zapis wyceny i zapis awaryjny."""

    def test_druga_proba_nie_tworzy_drugiego_zamowienia(self, aplikacja, monkeypatch):
        def zachowanie(quote, _licznik):
            # Tak wygląda wynik serwisu po D4: zamówienie w BaseLinkerze JEST,
            # ale ani numer, ani wpis w logu nie trafiły do bazy.
            return {'success': False, 'error': 'Lost connection to MySQL server',
                    'niepewne': False, 'zamowienie_utworzone': True,
                    'order_id': 900}

        wywolania = _atrapa(monkeypatch, zachowanie)
        wycena = _zasiej()

        pierwszy = _zamow(wycena)
        drugi = _zamow(wycena)

        assert pierwszy['zamowienie_utworzone'] is True
        assert drugi['ok'] is False
        assert len(wywolania) == 1, 'DRUGIE realne zamówienie w BaseLinkerze'

    def test_strona_po_odswiezeniu_nie_pokazuje_przycisku(self, aplikacja, monkeypatch):
        # Ten sam stan, z którego sonda D4 czytała `mozna_zamowic=True`.
        _atrapa(monkeypatch, lambda q, n: {
            'success': False, 'error': 'Lost connection', 'niepewne': False,
            'zamowienie_utworzone': True, 'order_id': 900})
        wycena = _zasiej()

        _zamow(wycena)

        odswiezona = Quote.query.get(wycena.id)
        assert checkout_service.wisi_nierozstrzygnieta_proba(odswiezona) is True


class TestPadnietyZapisZnacznikaPoTimeoucie:
    """Sonda D3b recenzenta: timeout, po którym pada zapis samego znacznika."""

    def test_druga_proba_nie_tworzy_drugiego_zamowienia(self, aplikacja, monkeypatch):
        def zachowanie(quote, _licznik):
            # Serwis nie zdołał dopisać wpisu `uncertain` (sesja zerwana),
            # więc log jest PUSTY — jedyną obroną zostaje znacznik na wycenie.
            return {'success': False, 'error': 'ReadTimeout',
                    'niepewne': True, 'zamowienie_utworzone': False,
                    'order_id': None}

        wywolania = _atrapa(monkeypatch, zachowanie)
        wycena = _zasiej()

        pierwszy = _zamow(wycena)

        # Sedno D3b: kasujemy WSZYSTKIE wpisy w logu, czyli odtwarzamy stan,
        # w którym zapis znacznika w logu padł razem z sesją. Zostaje dokładnie
        # to, co miało przeżyć awarię — znacznik na wierszu wyceny.
        BaselinkerOrderLog.query.delete()
        db.session.commit()

        drugi = _zamow(wycena)

        assert pierwszy['niepewne'] is True
        assert drugi['ok'] is False
        # Znacznik jest świeży, więc komunikat brzmi „przetwarzamy", a nie
        # „nie wiemy" — obie odmowy blokują tak samo i żadna nie wpuszcza
        # drugiego żądania do BaseLinkera.
        assert drugi['error'] == 'PROBA_W_TOKU'
        assert len(wywolania) == 1, 'DRUGIE realne zamówienie w BaseLinkerze'

    def test_bez_kasowania_logu_klient_slyszy_od_razu_ze_nie_wiemy(
            self, aplikacja, monkeypatch):
        # Gdy wpis o nierozstrzygniętej próbie JEST w bazie, wiemy więcej niż
        # z samego znacznika: próba się skończyła i skończyła się źle.
        _atrapa(monkeypatch, lambda q, n: {
            'success': False, 'error': 'ReadTimeout', 'niepewne': True,
            'zamowienie_utworzone': False, 'order_id': None})
        wycena = _zasiej()

        _zamow(wycena)
        drugi = _zamow(wycena)

        assert BaselinkerOrderLog.query.filter_by(
            status=STATUS_PROBA_NIEPEWNA).count() == 1
        assert drugi['error'] == 'NIEPEWNA_PROBA'
        assert drugi['niepewne'] is True


class TestStanProby:
    """Rozróżnienie „w toku" od „nie wiemy" — obie blokują, ale mówią co innego."""

    def test_swieza_proba_to_proba_w_toku(self, aplikacja):
        wycena = _zasiej()
        wycena.order_attempt_started_at = datetime.utcnow()
        db.session.commit()

        assert checkout_service.stan_proby(wycena) == checkout_service.PROBA_W_TOKU

    def test_stara_proba_to_proba_nierozstrzygnieta(self, aplikacja):
        wycena = _zasiej()
        wycena.order_attempt_started_at = (
            datetime.utcnow() - timedelta(seconds=checkout_service.PROG_PROBY_W_TOKU_S + 5))
        db.session.commit()

        assert checkout_service.stan_proby(wycena) == checkout_service.PROBA_NIEPEWNA

    def test_wpis_uncertain_w_logu_dalej_blokuje(self, aplikacja):
        # Zgodność wstecz: wpis w logu był dotąd jedynym znacznikiem i nadal
        # ma blokować — znacznik na wycenie go uzupełnia, a nie zastępuje.
        wycena = _zasiej()
        db.session.add(BaselinkerOrderLog(
            quote_id=wycena.id, action='create_order',
            status=STATUS_PROBA_NIEPEWNA))
        db.session.commit()

        assert checkout_service.stan_proby(wycena) == checkout_service.PROBA_NIEPEWNA

    def test_czysta_wycena_nie_ma_zadnej_proby(self, aplikacja):
        assert checkout_service.stan_proby(_zasiej()) is None


class TestBladBazyPrzedWywolaniem:
    """Sonda W2: żądanie, które nie dotarło do BaseLinkera, nie może straszyć."""

    def test_padnieta_blokada_nie_wola_baselinkera_i_nie_klamie(
            self, aplikacja, monkeypatch):
        from sqlalchemy.exc import OperationalError

        def padnij(_quote):
            raise OperationalError('SELECT ... FOR UPDATE', {},
                                   Exception('Lock wait timeout exceeded'))

        wywolania = _atrapa(monkeypatch, lambda q, n: {'success': True, 'order_id': 900})
        monkeypatch.setattr(checkout_service, 'zablokuj_wycene', padnij)
        wycena = _zasiej()

        wynik = _zamow(wycena)

        assert wynik['ok'] is False
        assert wynik['error'] == 'BLAD_BAZY'
        # Do BaseLinkera nie poszło NIC, więc ani „nie wiemy", ani „zamówienie jest".
        assert wynik['niepewne'] is False
        assert wynik['zamowienie_utworzone'] is False
        assert wywolania == []
