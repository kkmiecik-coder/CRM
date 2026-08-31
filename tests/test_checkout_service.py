# -*- coding: utf-8 -*-
"""
Składanie zamówienia przez klienta — idempotencja i bramka kwalifikacji.

Najgroźniejsza pułapka checkoutu publicznego: create_order_from_quote nie ma
ŻADNEJ idempotencji (brak guardu na base_linker_order_id, brak UNIQUE, brak
locka). Podwójne kliknięcie tworzy dwa realne zamówienia w BaseLinkerze,
a drugie nadpisuje base_linker_order_id — pierwsze zostaje osierocone.

Testy dzielą się na dwie grupy:

1. TestZlozZamowienieKlienta — decyzje serwisu na atrapach (kogo wpuszcza,
   kogo odrzuca, ile razy woła BaseLinkera). `zablokuj_wycene` podmieniony,
   więc ta grupa NIE mówi nic o tym, skąd wzięty jest stan wyceny.

2. TestBlokadaWiersza — prawdziwa sesja SQLAlchemy na SQLite in-memory.
   SQLite IGNORUJE `FOR UPDATE`, więc tu nie da się udowodnić blokady bazy.
   Dowodzimy właściwości, która jest po stronie aplikacji i którą łatwo
   stracić: guard czyta stan wyceny ŚWIEŻO Z BAZY, a nie z obiektu podanego
   w argumencie. Bez tego blokada na MySQL-u byłaby bezużyteczna — drugie
   żądanie doczekałoby swojej kolei, po czym i tak przeczytałoby własną,
   nieaktualną kopię wiersza (identity map) i złożyło drugie zamówienie.
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.quotes.services import checkout_service  # noqa: E402


class _Wycena(SimpleNamespace):
    def is_eligible_for_order(self):
        return self._kwalifikuje


def _wycena(**nadpisania):
    dane = {
        "id": 1,
        "quote_number": "337/08/26/W",
        "quote_type": "brutto",
        "courier_name": "DPD",
        "shipping_cost_netto": None,
        "shipping_cost_brutto": None,
        "base_linker_order_id": None,
        "baselinker_order_page": None,
        "_kwalifikuje": True,
    }
    dane.update(nadpisania)
    return _Wycena(**dane)


@pytest.fixture()
def serwis_bl(monkeypatch):
    """Podstawia atrapę BaselinkerService; zlicza wywołania create_order_from_quote."""
    wywolania = []

    class _Atrapa:
        def __init__(self, *a, **k):
            pass

        def create_order_from_quote(self, quote, user_id, config):
            wywolania.append({"quote": quote, "user_id": user_id, "config": config})
            quote.base_linker_order_id = "555"
            quote.baselinker_order_page = "https://blsklep.pl/z/xyz"
            return {"success": True, "order_id": 555, "message": "ok"}

    monkeypatch.setattr(checkout_service, "BaselinkerService", _Atrapa)
    monkeypatch.setattr(checkout_service, "zablokuj_wycene", lambda q: q)
    # Znacznik nierozstrzygniętej próby ma własne testy (niżej, na prawdziwej
    # sesji) — ta grupa chodzi bez bazy, więc odpowiada „brak takiej próby".
    monkeypatch.setattr(checkout_service, "istnieje_nierozstrzygnieta_proba",
                        lambda quote_id: False)
    # commit() — znacznik próby zapisuje się PRZED wywołaniem BaseLinkera
    # i musi się zacommitować, inaczej nie przeżyłby awarii, która nastąpi później.
    monkeypatch.setattr(checkout_service.db, "session",
                        SimpleNamespace(rollback=lambda: None,
                                        commit=lambda: None))
    return wywolania


class TestZlozZamowienieKlienta:
    def test_tworzy_zamowienie_i_zwraca_link_strony_zamowienia(self, serwis_bl):
        wynik = checkout_service.zloz_zamowienie_klienta(
            _wycena(), order_source_id=99001, bot_user_id=55)

        assert wynik["ok"] is True
        assert wynik["order_id"] == 555
        assert wynik["order_page_url"] == "https://blsklep.pl/z/xyz"
        assert wynik["duplikat"] is False
        assert len(serwis_bl) == 1

    def test_drugie_zadanie_nie_tworzy_drugiego_zamowienia(self, serwis_bl):
        # Wycena ma juz zamowienie — powtorka zwraca istniejace, nie wola BaseLinkera.
        wycena = _wycena(base_linker_order_id="555",
                         baselinker_order_page="https://blsklep.pl/z/xyz")

        wynik = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=55)

        assert wynik["ok"] is True
        assert wynik["order_id"] == 555
        assert wynik["order_page_url"] == "https://blsklep.pl/z/xyz"
        assert wynik["duplikat"] is True
        assert len(serwis_bl) == 0

    def test_powtorka_dziala_takze_dla_nieliczbowego_id_zamowienia(self, serwis_bl):
        # base_linker_order_id to kolumna tekstowa. Śmieć w niej nie może wywalać
        # powtórki wyjątkiem — zamówienie istnieje i klient ma to zobaczyć.
        wycena = _wycena(base_linker_order_id="BL-555")

        wynik = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=55)

        assert wynik["ok"] is True
        assert wynik["duplikat"] is True
        assert wynik["order_id"] == "BL-555"
        assert len(serwis_bl) == 0

    def test_wycena_niekwalifikujaca_sie_jest_odrzucana(self, serwis_bl):
        wynik = checkout_service.zloz_zamowienie_klienta(
            _wycena(_kwalifikuje=False), order_source_id=99001, bot_user_id=55)

        assert wynik["ok"] is False
        assert wynik["error"] == "NIEKWALIFIKOWANA"
        assert len(serwis_bl) == 0

    def test_blad_baselinkera_przechodzi_do_wywolujacego(self, monkeypatch):
        class _AtrapaBledna:
            def __init__(self, *a, **k):
                pass

            def create_order_from_quote(self, quote, user_id, config):
                return {"success": False, "error": "Brak tokenu API"}

        monkeypatch.setattr(checkout_service, "BaselinkerService", _AtrapaBledna)
        monkeypatch.setattr(checkout_service, "zablokuj_wycene", lambda q: q)
        monkeypatch.setattr(checkout_service, "istnieje_nierozstrzygnieta_proba",
                            lambda quote_id: False)
        monkeypatch.setattr(checkout_service.db, "session",
                            SimpleNamespace(rollback=lambda: None,
                                            commit=lambda: None))

        wynik = checkout_service.zloz_zamowienie_klienta(
            _wycena(), order_source_id=99001, bot_user_id=55)

        assert wynik["ok"] is False
        assert wynik["error"] == "Brak tokenu API"
        assert wynik["order_id"] is None

    def test_po_nieudanej_probie_kolejna_moze_zlozyc_zamowienie(self, monkeypatch):
        # Nieudana próba NIE może zablokować wyceny na zawsze: skoro zamówienie
        # nie powstało, klient musi móc kliknąć jeszcze raz.
        wywolania = []

        class _AtrapaRazBledna:
            def __init__(self, *a, **k):
                pass

            def create_order_from_quote(self, quote, user_id, config):
                wywolania.append(config)
                if len(wywolania) == 1:
                    return {"success": False, "error": "Timeout API"}
                quote.base_linker_order_id = "556"
                quote.baselinker_order_page = "https://blsklep.pl/z/abc"
                return {"success": True, "order_id": 556}

        monkeypatch.setattr(checkout_service, "BaselinkerService", _AtrapaRazBledna)
        monkeypatch.setattr(checkout_service, "zablokuj_wycene", lambda q: q)
        monkeypatch.setattr(checkout_service, "istnieje_nierozstrzygnieta_proba",
                            lambda quote_id: False)
        monkeypatch.setattr(checkout_service.db, "session",
                            SimpleNamespace(rollback=lambda: None,
                                            commit=lambda: None))

        wycena = _wycena()
        pierwszy = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=55)
        drugi = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=55)

        assert pierwszy["ok"] is False
        assert drugi["ok"] is True and drugi["duplikat"] is False
        assert drugi["order_id"] == 556
        assert len(wywolania) == 2

    def test_konfiguracja_niesie_zrodlo_zamowien(self, serwis_bl):
        checkout_service.zloz_zamowienie_klienta(
            _wycena(), order_source_id=99001, bot_user_id=55)

        assert serwis_bl[0]["config"]["order_source_id"] == 99001
        assert serwis_bl[0]["user_id"] == 55


# =============================================================================
# Blokada wiersza na prawdziwej sesji SQLAlchemy (SQLite in-memory)
# =============================================================================

from flask import Flask  # noqa: E402
from sqlalchemy.orm.attributes import set_committed_value  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from extensions import db  # noqa: E402
from modules.calculator.models import (  # noqa: E402
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.users.models import User  # noqa: E402
from modules.clients.models import Client  # noqa: E402

import modules.quotes.models  # noqa: E402,F401 — rejestr mapperów
from modules.quotes.models import QuoteStatus  # noqa: E402
from modules.baselinker.models import (  # noqa: E402
    BaselinkerOrderLog, STATUS_PROBA_NIEPEWNA,
)

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


def _zasiej_wycene(numer='400/08/26/W', token='TOKENIDEMPOTENCJA0000000000001',
                   base_linker_order_id=None):
    klient = Client(client_number=f'K-{numer}', client_name='Jan Testowy',
                    email='jan@example.pl', phone='601234567')
    db.session.add(klient)
    db.session.flush()
    wycena = Quote(quote_number=numer, public_token=token, status_id=3,
                   client_id=klient.id, quote_type='brutto', courier_name='DPD',
                   base_linker_order_id=base_linker_order_id)
    db.session.add(wycena)
    db.session.flush()
    db.session.add(QuoteItem(
        quote_id=wycena.id, product_index=1, variant_code='dab-lity-ab',
        length_cm=100, width_cm=50, thickness_cm=3,
        price_netto=100.0, price_brutto=123.0, is_selected=True))
    db.session.commit()
    return wycena


class TestBlokadaWiersza:
    """Co te testy dowodzą, a czego nie.

    DOWODZĄ: guard idempotencji ocenia stan wzięty świeżo z bazy (SELECT pod
    blokadą), a nie wartość atrybutu obiektu przekazanego w argumencie.

    NIE DOWODZĄ: że dwa równoległe procesy się serializują — SQLite ignoruje
    `FOR UPDATE`, a testy chodzą w jednym wątku i jednym połączeniu. Wzajemne
    wykluczanie zapewnia dopiero InnoDB na produkcji; tutaj sprawdzamy warunek
    konieczny, bez którego ta blokada i tak by nie zadziałała.
    """

    def test_stan_z_bazy_wygrywa_z_nieaktualnym_obiektem_w_pamieci(
            self, aplikacja, monkeypatch):
        wywolania = []

        class _Atrapa:
            def __init__(self, *a, **k):
                pass

            def create_order_from_quote(self, quote, user_id, config):
                wywolania.append(config)
                return {"success": True, "order_id": 999}

        monkeypatch.setattr(checkout_service, "BaselinkerService", _Atrapa)

        wycena = _zasiej_wycene()
        wycena.base_linker_order_id = '555'
        wycena.baselinker_order_page = 'https://blsklep.pl/z/pierwsze'
        db.session.commit()

        # Tak wygląda wycena w drugim, równoległym żądaniu: jego sesja wczytała
        # wiersz ZANIM pierwsze żądanie zapisało numer zamówienia, więc obiekt
        # w pamięci wciąż twierdzi, że zamówienia nie ma. set_committed_value
        # ustawia tę nieaktualną wartość bez brudzenia obiektu — dokładnie tak,
        # jak wyglądałby odczyt ze snapshotu transakcji.
        set_committed_value(wycena, 'base_linker_order_id', None)
        set_committed_value(wycena, 'baselinker_order_page', None)
        assert wycena.base_linker_order_id is None

        wynik = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=None)

        assert wynik["duplikat"] is True, "guard uwierzył nieaktualnemu obiektowi"
        assert wynik["order_id"] == 555
        assert wynik["order_page_url"] == 'https://blsklep.pl/z/pierwsze'
        assert wywolania == [], "drugie realne zamówienie w BaseLinkerze"

    def test_kwalifikujaca_sie_wycena_przechodzi_przez_blokade(
            self, aplikacja, monkeypatch):
        # Kontrola negatywna: blokada nie może odrzucać poprawnych zamówień
        # (i musi dać się wykonać na realnej sesji, nie tylko na atrapie).
        wywolania = []

        class _Atrapa:
            def __init__(self, *a, **k):
                pass

            def create_order_from_quote(self, quote, user_id, config):
                wywolania.append(config)
                quote.base_linker_order_id = '777'
                quote.baselinker_order_page = 'https://blsklep.pl/z/nowe'
                db.session.commit()
                return {"success": True, "order_id": 777}

        monkeypatch.setattr(checkout_service, "BaselinkerService", _Atrapa)

        wycena = _zasiej_wycene(numer='401/08/26/W',
                                token='TOKENIDEMPOTENCJA0000000000002')

        wynik = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=None)

        assert wynik["ok"] is True and wynik["duplikat"] is False
        assert wynik["order_id"] == 777
        assert wynik["order_page_url"] == 'https://blsklep.pl/z/nowe'
        assert len(wywolania) == 1
        assert wywolania[0]["delivery_method"] == 'DPD'

    def test_kolejne_zadanie_po_zapisanym_zamowieniu_nie_wola_baselinkera(
            self, aplikacja, monkeypatch):
        # Ścieżka „klient klika drugi raz po udanym zamówieniu" — tym razem
        # w całości przez bazę, bez podmiany zablokuj_wycene.
        wywolania = []

        class _Atrapa:
            def __init__(self, *a, **k):
                pass

            def create_order_from_quote(self, quote, user_id, config):
                wywolania.append(config)
                quote.base_linker_order_id = '888'
                quote.baselinker_order_page = 'https://blsklep.pl/z/osiem'
                db.session.commit()
                return {"success": True, "order_id": 888}

        monkeypatch.setattr(checkout_service, "BaselinkerService", _Atrapa)

        wycena = _zasiej_wycene(numer='402/08/26/W',
                                token='TOKENIDEMPOTENCJA0000000000003')

        pierwszy = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=None)
        drugi = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=None)

        assert pierwszy["duplikat"] is False
        assert drugi["duplikat"] is True
        assert drugi["order_id"] == 888
        assert drugi["order_page_url"] == 'https://blsklep.pl/z/osiem'
        assert len(wywolania) == 1


class TestNierozstrzygnietaProba:
    """Znacznik trwały tam, gdzie numeru zamówienia jeszcze nie ma.

    Po timeoucie BaseLinkera nie wiemy, czy zamówienie powstało, i nie mamy
    jego numeru — guard idempotencji jest wtedy ślepy. Blokadę trzymał tylko
    JavaScript, a odświeżenie strony kasowało ją w całości.
    """

    def _atrapa(self, monkeypatch, wywolania):
        class _Atrapa:
            def __init__(self, *a, **k):
                pass

            def create_order_from_quote(self, quote, user_id, config):
                wywolania.append(config)
                quote.base_linker_order_id = '999'
                db.session.commit()
                return {"success": True, "order_id": 999}

        monkeypatch.setattr(checkout_service, "BaselinkerService", _Atrapa)

    def _znacznik(self, quote_id, status=STATUS_PROBA_NIEPEWNA):
        db.session.add(BaselinkerOrderLog(
            quote_id=quote_id, action='create_order', status=status))
        db.session.commit()

    def test_nierozstrzygnieta_proba_nie_wpuszcza_do_baselinkera(
            self, aplikacja, monkeypatch):
        wywolania = []
        self._atrapa(monkeypatch, wywolania)
        wycena = _zasiej_wycene(numer='403/08/26/W',
                                token='TOKENIDEMPOTENCJA0000000000004')
        self._znacznik(wycena.id)

        wynik = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=None)

        assert wynik["ok"] is False
        assert wynik["error"] == "NIEPEWNA_PROBA"
        assert wynik["niepewne"] is True
        assert wywolania == [], "drugie realne zamówienie w BaseLinkerze"

    def test_zwykly_blad_nie_blokuje_kolejnej_proby(self, aplikacja, monkeypatch):
        # Kontrola negatywna: wpis 'error' znaczy „zamówienia na pewno nie ma",
        # więc powtórka po nim musi przechodzić.
        wywolania = []
        self._atrapa(monkeypatch, wywolania)
        wycena = _zasiej_wycene(numer='404/08/26/W',
                                token='TOKENIDEMPOTENCJA0000000000005')
        self._znacznik(wycena.id, status='error')

        wynik = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=None)

        assert wynik["ok"] is True
        assert len(wywolania) == 1

    def test_znacznik_z_innej_wyceny_nie_blokuje(self, aplikacja, monkeypatch):
        wywolania = []
        self._atrapa(monkeypatch, wywolania)
        obca = _zasiej_wycene(numer='405/08/26/W',
                              token='TOKENIDEMPOTENCJA0000000000006')
        wycena = _zasiej_wycene(numer='406/08/26/W',
                                token='TOKENIDEMPOTENCJA0000000000007')
        self._znacznik(obca.id)

        wynik = checkout_service.zloz_zamowienie_klienta(
            wycena, order_source_id=99001, bot_user_id=None)

        assert wynik["ok"] is True
        assert len(wywolania) == 1
