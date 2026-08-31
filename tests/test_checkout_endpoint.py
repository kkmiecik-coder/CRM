# -*- coding: utf-8 -*-
"""
Publiczny endpoint składania zamówienia + bramka tożsamości.

Aplikacja nie ma CSRF, więc jedyną autoryzacją tego endpointu jest
public_token wyceny plus zgodność email LUB telefonu z klientem wyceny.
Bramkę testujemy jako czystą funkcję (bez Flaska), zgodnie z konwencją
tests/test_client_quote_api.py, a sam endpoint — na minimalnym Flasku
z SQLite in-memory (konwencja tests/test_bot_api_by_token_integration.py),
bo to on tworzy REALNE zamówienia i tu pomyłka kosztuje pieniądze.

BaselinkerService jest zawsze atrapą — żaden test nie dotyka BaseLinkera.
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.quotes import routers  # noqa: E402

dane_pasuja_do_klienta = routers.dane_pasuja_do_klienta
dopasowanie_danych_klienta = routers.dopasowanie_danych_klienta


def _klient(email=None, phone=None):
    return SimpleNamespace(email=email, phone=phone)


class TestBramkaTozsamosci:
    def test_zgodny_email_przepuszcza(self):
        assert dane_pasuja_do_klienta(
            _klient(email="Jan@Example.PL"), "jan@example.pl", "") is True

    def test_zgodny_telefon_przepuszcza(self):
        assert dane_pasuja_do_klienta(
            _klient(phone="+48 601 234 567"), "", "601-234-567") is True

    def test_obcy_email_i_obcy_telefon_odrzucone(self):
        assert dane_pasuja_do_klienta(
            _klient(email="jan@example.pl", phone="601234567"),
            "ewa@example.pl", "509999999") is False

    def test_pusty_klient_nie_przepuszcza_pustych_danych(self):
        # Bez tego pusty klient + puste wejscie dawaloby "zgodnosc" i otwieral endpoint.
        assert dane_pasuja_do_klienta(_klient(), "", "") is False

    def test_telefon_krotszy_niz_dziewiec_cyfr_nie_przepuszcza(self):
        assert dane_pasuja_do_klienta(
            _klient(phone="601234567"), "", "1234") is False

    def test_zwraca_osobno_zgodnosc_emaila_i_telefonu(self):
        # client_accept_quote_with_data używa OBU flag osobno: zgodność telefonu
        # nie może uprawniać do nadpisania adresu email na kliencie (mail
        # z akceptacją idzie właśnie na ten adres). Sklejenie ich w jeden bool
        # otwiera przejęcie adresu przez kogoś, kto zna tylko numer telefonu.
        klient = _klient(email="jan@example.pl", phone="601234567")
        assert dopasowanie_danych_klienta(klient, "ewa@example.pl", "601234567") \
            == (False, True)
        assert dopasowanie_danych_klienta(klient, "jan@example.pl", "509999999") \
            == (True, False)


# =============================================================================
# Endpoint POST /quotes/api/client/quote/<token>/order
# =============================================================================

from datetime import datetime  # noqa: E402

from flask import Flask  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from extensions import db  # noqa: E402
from modules.baselinker.models import BaselinkerConfig, BaselinkerOrderLog  # noqa: E402
from modules.calculator.models import (  # noqa: E402
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: E402
from modules.quotes import quotes_bp  # noqa: E402
from modules.quotes.models import QuoteStatus  # noqa: E402
from modules.quotes.services import checkout_service  # noqa: E402
from modules.users.models import User  # noqa: E402

TOKEN = 'TOKENCHECKOUT000000000000000001'
ZRODLO_DEBUS = 85727

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
    app.config['BOT_USER_ID'] = None
    app.register_blueprint(quotes_bp, url_prefix='/quotes')
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABELE)
        yield app
        db.session.remove()


@pytest.fixture()
def klient_http(aplikacja):
    return aplikacja.test_client()


@pytest.fixture()
def baselinker(monkeypatch):
    """Atrapa BaselinkerService zachowująca się jak realny serwis po sukcesie."""
    wywolania = []
    zachowanie = {'sukces': True, 'error': 'Brak tokenu API',
                  'niepewne': False}

    class _Atrapa:
        def __init__(self, *a, **k):
            pass

        def create_order_from_quote(self, quote, user_id, config):
            wywolania.append({'config': config, 'user_id': user_id,
                              'quote_id': quote.id})
            if not zachowanie['sukces']:
                return {'success': False, 'error': zachowanie['error'],
                        'niepewne': zachowanie['niepewne']}
            numer = 500 + len(wywolania)
            quote.base_linker_order_id = str(numer)
            quote.baselinker_order_page = f'https://blsklep.pl/z/{numer}'
            quote.status_id = 4          # „Złożone" — jak realny serwis
            db.session.commit()
            return {'success': True, 'order_id': numer}

    monkeypatch.setattr(checkout_service, 'BaselinkerService', _Atrapa)
    return SimpleNamespace(wywolania=wywolania, zachowanie=zachowanie)


def _zasiej(status_id=1, is_client_editable=True, ze_zrodlem=True,
            email='jan@example.pl', phone='601234567',
            nazwa_zrodla='Dębuś VPS'):
    db.session.add(QuoteStatus(id=3, name='Zaakceptowane'))
    db.session.add(QuoteStatus(id=4, name='Złożone'))
    if ze_zrodlem:
        db.session.add(BaselinkerConfig(
            config_type='order_source', baselinker_id=ZRODLO_DEBUS,
            name=nazwa_zrodla, is_default=False, is_active=True, sort_order=100,
            created_at=datetime(2026, 8, 30), updated_at=datetime(2026, 8, 30)))
    klient = Client(client_number='K-1', client_name='Jan Testowy',
                    email=email, phone=phone)
    db.session.add(klient)
    db.session.flush()
    wycena = Quote(quote_number='410/08/26/W', public_token=TOKEN,
                   status_id=status_id, client_id=klient.id, quote_type='brutto',
                   courier_name='DPD', shipping_cost_brutto=123.0,
                   is_client_editable=is_client_editable)
    if status_id == 3:
        wycena.acceptance_date = datetime(2026, 8, 30, 12, 0, 0)
        wycena.accepted_by_email = email
    db.session.add(wycena)
    db.session.flush()
    db.session.add(QuoteItem(
        quote_id=wycena.id, product_index=1, variant_code='dab-lity-ab',
        length_cm=100, width_cm=50, thickness_cm=3,
        price_netto=100.0, price_brutto=123.0, is_selected=True))
    db.session.commit()
    return wycena.id


def _dane(**nadpisania):
    dane = {
        'email': 'jan@example.pl',
        'phone': '601234567',
        'is_self_pickup': True,
        'wants_invoice': False,
        'akceptacja_regulaminu': True,
    }
    dane.update(nadpisania)
    return dane


def _zamow(klient_http, token=TOKEN, **nadpisania):
    return klient_http.post(f'/quotes/api/client/quote/{token}/order',
                            json=_dane(**nadpisania))


class TestEndpointZamowienia:
    def test_klient_sklada_zamowienie_i_dostaje_link(self, aplikacja, klient_http,
                                                     baselinker):
        _zasiej()

        odpowiedz = _zamow(klient_http)

        assert odpowiedz.status_code == 200
        body = odpowiedz.get_json()
        assert body['ok'] is True
        assert body['order_id'] == 501
        assert body['quote_number'] == '410/08/26/W'
        assert body['order_page_url'] == 'https://blsklep.pl/z/501'
        assert body['duplikat'] is False
        # Źródło „Dębuś" z bazy trafia do konfiguracji zamówienia.
        assert baselinker.wywolania[0]['config']['order_source_id'] == ZRODLO_DEBUS
        with aplikacja.app_context():
            wycena = Quote.query.filter_by(public_token=TOKEN).first()
            assert wycena.base_linker_order_id == '501'
            assert wycena.status_id == 4
            assert wycena.is_client_editable is False   # akceptacja przeszła po drodze

    def test_wycena_juz_zaakceptowana_daje_sie_zamowic(self, aplikacja, klient_http,
                                                       baselinker):
        # Przypadek właściciela: wycena zaakceptowana wcześniej, przycisk „Zamów"
        # musi ją dowieźć do zamówienia, a nie odbić jako „już zaakceptowana".
        _zasiej(status_id=3, is_client_editable=False)

        odpowiedz = _zamow(klient_http)

        assert odpowiedz.status_code == 200
        assert odpowiedz.get_json()['ok'] is True
        assert len(baselinker.wywolania) == 1

    def test_podwojne_kliniecie_tworzy_jedno_zamowienie(self, aplikacja, klient_http,
                                                        baselinker):
        _zasiej()

        pierwsza = _zamow(klient_http)
        druga = _zamow(klient_http)

        assert pierwsza.status_code == 200 and druga.status_code == 200
        assert pierwsza.get_json()['duplikat'] is False
        assert druga.get_json()['duplikat'] is True
        assert druga.get_json()['order_id'] == 501
        assert druga.get_json()['order_page_url'] == 'https://blsklep.pl/z/501'
        assert len(baselinker.wywolania) == 1, 'drugie realne zamówienie w BaseLinkerze'

    def test_brak_zgody_na_warunki_nie_zamawia(self, aplikacja, klient_http,
                                               baselinker):
        _zasiej()

        odpowiedz = _zamow(klient_http, akceptacja_regulaminu=False)

        assert odpowiedz.status_code == 400
        assert baselinker.wywolania == []
        with aplikacja.app_context():
            wycena = Quote.query.filter_by(public_token=TOKEN).first()
            assert wycena.base_linker_order_id is None
            assert wycena.is_client_editable is True   # akceptacja też nie przeszła

    def test_obce_dane_kontaktowe_nie_zamawiaja(self, aplikacja, klient_http,
                                                baselinker):
        _zasiej()

        odpowiedz = _zamow(klient_http, email='ewa@example.pl', phone='509999999')

        assert odpowiedz.status_code == 403
        assert baselinker.wywolania == []
        with aplikacja.app_context():
            assert Quote.query.filter_by(
                public_token=TOKEN).first().base_linker_order_id is None

    def test_nieznany_token_daje_404(self, aplikacja, klient_http, baselinker):
        _zasiej()

        odpowiedz = _zamow(klient_http, token='NIEISTNIEJACYTOKEN000000000001')

        assert odpowiedz.status_code == 404
        assert baselinker.wywolania == []

    def test_brak_zrodla_debus_nie_tworzy_zamowienia(self, aplikacja, klient_http,
                                                     baselinker):
        # Bez źródła zamówienie wpadłoby do BaseLinkera z cudzym źródłem albo
        # z żadnym — wolimy odmówić, niż zaśmiecić realny system zamówień.
        _zasiej(ze_zrodlem=False)

        odpowiedz = _zamow(klient_http)

        # 503, nie 500: to nie jest awaria żądania klienta, tylko brakująca
        # konfiguracja po naszej stronie — i klient dostaje o tym zdanie
        # po polsku, a nie samo „Błąd konfiguracji zamówień".
        assert odpowiedz.status_code == 503
        assert baselinker.wywolania == []
        body = odpowiedz.get_json()
        assert 'NIE zostało złożone' in body['error']
        assert '410/08/26/W' in body['error']
        # Zamówienie na pewno nie powstało — klient może spróbować ponownie.
        assert body['niepewne'] is False
        # I nic po drodze się nie zatwierdziło: brak konfiguracji nie może
        # zostawiać wyceny zaakceptowanej (z mailem do klienta) bez zamówienia.
        with aplikacja.app_context():
            wycena = Quote.query.filter_by(public_token=TOKEN).first()
            assert wycena.is_client_editable is True
            assert wycena.base_linker_order_id is None

    def test_zrodlo_znajdowane_po_id_a_nie_po_nazwie(self, aplikacja, klient_http,
                                                     baselinker):
        # Nazwa źródła to pole redagowalne w panelu BaseLinkera. Gdy kod szukał
        # po niej, samo przemianowanie źródła kładło checkout. Wiąże nas
        # baselinker_id — ta sama stała, którą wstawia migracja.
        _zasiej(nazwa_zrodla='Zamówienia ze strony')

        odpowiedz = _zamow(klient_http)

        assert odpowiedz.status_code == 200
        assert baselinker.wywolania[0]['config']['order_source_id'] == ZRODLO_DEBUS

    def test_blad_baselinkera_nie_udaje_sukcesu_i_pozwala_powtorzyc(
            self, aplikacja, klient_http, baselinker):
        _zasiej()
        baselinker.zachowanie['sukces'] = False

        odpowiedz = _zamow(klient_http)

        assert odpowiedz.status_code == 502
        # Komunikat API BaseLinkera nie wychodzi na publiczną stronę klienta.
        assert 'Brak tokenu API' not in odpowiedz.get_json()['error']
        with aplikacja.app_context():
            assert Quote.query.filter_by(
                public_token=TOKEN).first().base_linker_order_id is None

        # Po naprawie usterki klient musi móc kliknąć jeszcze raz.
        baselinker.zachowanie['sukces'] = True
        powtorka = _zamow(klient_http)
        assert powtorka.status_code == 200
        assert powtorka.get_json()['duplikat'] is False
        assert len(baselinker.wywolania) == 2

    def test_zgodny_telefon_nie_nadpisuje_adresu_email_klienta(
            self, aplikacja, klient_http, baselinker):
        # Regresja po wydzieleniu bramki: akceptacja (wołana w środku checkoutu)
        # uzupełnia dane klienta na podstawie OSOBNYCH flag. Zgodny telefon nie
        # może podmienić adresu email — na ten adres idzie mail z akceptacją.
        _zasiej()

        odpowiedz = _zamow(klient_http, email='ewa@example.pl')

        assert odpowiedz.status_code == 200
        with aplikacja.app_context():
            klient = Client.query.first()
            assert klient.email == 'jan@example.pl'
            assert klient.phone == '601234567'

    def test_blad_akceptacji_wraca_do_klienta_dokladnie(self, aplikacja,
                                                        klient_http, baselinker):
        # Bramka tożsamości przepuszcza na sam telefon, ale akceptacja wymaga
        # obu pól. Klient ma dostać konkretny powód, a nie ogólne
        # „nie kwalifikuje się", i żadne zamówienie nie ma prawa powstać.
        _zasiej()

        odpowiedz = _zamow(klient_http, email='')

        assert odpowiedz.status_code == 400
        assert odpowiedz.get_json()['error'] == 'Email jest wymagany'
        assert baselinker.wywolania == []
        with aplikacja.app_context():
            assert Quote.query.filter_by(
                public_token=TOKEN).first().base_linker_order_id is None

    def test_akceptacja_przegrana_w_wyscigu_nie_blokuje_zamowienia(
            self, aplikacja, klient_http, baselinker, monkeypatch):
        # Podwójne kliknięcie: równoległe żądanie zdążyło zaakceptować wycenę,
        # więc NASZA akceptacja odbija się z 400 „już zaakceptowana". Zamówienie
        # ma i tak powstać — inaczej klient widzi błąd, choć wszystko jest gotowe.
        _zasiej()

        def _akceptacja_przegrana(token):
            from flask import jsonify as _jsonify
            wycena = Quote.query.filter_by(public_token=token).first()
            wycena.status_id = 3
            wycena.is_client_editable = False
            wycena.acceptance_date = datetime(2026, 8, 30, 12, 0, 0)
            db.session.commit()
            return _jsonify({"error": "Wycena została już zaakceptowana"}), 400

        monkeypatch.setattr(routers, 'client_accept_quote_with_data',
                            _akceptacja_przegrana)

        odpowiedz = _zamow(klient_http)

        assert odpowiedz.status_code == 200
        assert odpowiedz.get_json()['ok'] is True
        assert len(baselinker.wywolania) == 1

    def test_wycena_bez_wybranych_pozycji_jest_odrzucana(self, aplikacja,
                                                         klient_http, baselinker):
        _zasiej()
        with aplikacja.app_context():
            QuoteItem.query.update({'is_selected': False})
            db.session.commit()

        odpowiedz = _zamow(klient_http)

        assert odpowiedz.status_code == 400
        assert baselinker.wywolania == []


class TestKomunikatPoNieudanymZamowieniu:
    """D2 — klient ma wiedzieć, czy zamówienie powstało, czy nie."""

    def test_odmowa_baselinkera_mowi_wprost_ze_zamowienia_nie_ma(
            self, aplikacja, klient_http, baselinker):
        # API odpowiedziało i odmówiło — wiemy na pewno, że zamówienia nie ma.
        _zasiej()
        baselinker.zachowanie['sukces'] = False
        baselinker.zachowanie['niepewne'] = False

        body = _zamow(klient_http).get_json()

        assert body['niepewne'] is False
        assert 'NIE zostało złożone' in body['error']
        assert '410/08/26/W' in body['error']

    def test_zerwana_lacznosc_nie_twierdzi_ze_zamowienia_nie_ma(
            self, aplikacja, klient_http, baselinker):
        # Najgorszy przypadek: BaseLinker mógł zamówienie utworzyć, a odpowiedź
        # zginęła po drodze. Komunikat nie może twierdzić ani „zamówiliśmy",
        # ani „nie zamówiliśmy" — ma poprosić o kontakt i podać numer wyceny.
        _zasiej()
        baselinker.zachowanie['sukces'] = False
        baselinker.zachowanie['niepewne'] = True

        odpowiedz = _zamow(klient_http)
        body = odpowiedz.get_json()

        assert odpowiedz.status_code == 502
        assert body['niepewne'] is True
        assert '410/08/26/W' in body['error']
        assert 'nie wiemy' in body['error']
        # Żadnego rozstrzygnięcia w którąkolwiek stronę.
        assert 'NIE zostało złożone' not in body['error']
        # I wyraźny zakaz ponawiania — drugie kliknięcie to drugie realne
        # zamówienie, bo base_linker_order_id nie zdążył się zapisać.
        assert 'nie składaj' in body['error'].lower()


class TestZnacznikNiepewnosciWSerwisie:
    """Skąd bierze się `niepewne`: wyjątek transportowy w create_order_from_quote."""

    def _wycena(self):
        _zasiej()
        return Quote.query.filter_by(public_token=TOKEN).first()

    def _serwis(self, aplikacja, monkeypatch, wyjatek):
        from modules.baselinker.service import BaselinkerService
        serwis = BaselinkerService()
        monkeypatch.setattr(serwis, '_prepare_order_data', lambda quote, config: {})

        def _rzuc(method, parameters):
            raise wyjatek

        monkeypatch.setattr(serwis, '_make_request', _rzuc)
        return serwis

    def test_timeout_polaczenia_oznacza_wynik_jako_niepewny(self, aplikacja,
                                                            monkeypatch):
        import requests
        wycena = self._wycena()
        serwis = self._serwis(aplikacja, monkeypatch,
                              requests.exceptions.ReadTimeout('read timed out'))

        wynik = serwis.create_order_from_quote(wycena, None, {})

        assert wynik['success'] is False
        assert wynik['niepewne'] is True

    def test_blad_przed_wyslaniem_zadania_nie_jest_niepewny(self, aplikacja,
                                                            monkeypatch):
        # Wyjątek, który nie pochodzi z warstwy transportowej (np. brak
        # konfiguracji API), znaczy, że żądanie nigdy nie wyszło — zamówienia
        # na pewno nie ma i klient może spróbować ponownie.
        wycena = self._wycena()
        serwis = self._serwis(aplikacja, monkeypatch,
                              ValueError('Brak konfiguracji API Baselinker'))

        wynik = serwis.create_order_from_quote(wycena, None, {})

        assert wynik['success'] is False
        assert wynik['niepewne'] is False
