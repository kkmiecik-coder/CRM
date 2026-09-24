# -*- coding: utf-8 -*-
"""Endpointy układu pulpitu i wpływ układu na /api/analytics.

Fikstury jak w tests/test_analiza_widok.py: sidebar podmieniony zaślepką,
blueprint `production` rejestrowany naprawdę (szablon woła url_for po Chart.js).
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import reports_bp
from modules.reports.models_uklad import UkladDashboardu
from modules.reports.uklad import KATALOG, MAKS_KAFELKOW, UKLAD_DOMYSLNY, Instancja

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)


@compiles(LONGTEXT, 'sqlite')
def _longtext_jako_text(typ, kompilator, **kw):
    return 'TEXT'


from modules.production.models import ProductionOrder  # noqa: F401
from modules.users.models import User
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATYKA_PRODUKCJI = os.path.join(KORZEN, 'modules', 'production', 'static')

TYP_WYMIAROWY = next(k for k, t in KATALOG.items() if t.wymiarowy)
WYMIAR = KATALOG[TYP_WYMIAROWY].domyslny_wymiar
INNY_WYMIAR = 'caretaker' if WYMIAR != 'caretaker' else 'order_source'


@pytest.fixture()
def app(monkeypatch):
    from modules.users.services.permission_service import PermissionService
    monkeypatch.setattr(PermissionService, 'user_has_module_access',
                        staticmethod(lambda user_id, module_key: True))

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(reports_bp)
    produkcja = Blueprint('production', __name__, static_folder=STATYKA_PRODUKCJI,
                          static_url_path='/production/static')
    app.register_blueprint(produkcja, url_prefix='/production')
    app.jinja_loader = ChoiceLoader([
        DictLoader({'sidebar/sidebar.html': '<nav data-sidebar-zaslepka></nav>'}),
        app.jinja_loader,
    ])
    db.init_app(app)
    with app.app_context():
        db.create_all()
        db.session.add(User(email='kontroler@woodpower.pl', password='x',
                            role='admin', active=True))
        db.session.commit()
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    c = app.test_client()
    with c.session_transaction() as sesja:
        sesja['user_email'] = 'kontroler@woodpower.pl'
    return c


@pytest.fixture()
def uzytkownik(app):
    return User.query.filter_by(email='kontroler@woodpower.pl').first()


def zapisz(client, pozycje):
    return client.post('/reports/api/uklad', json={'uklad': pozycje})


# --- zapis ------------------------------------------------------------------

def test_zapis_poprawnego_ukladu_oddaje_200(client):
    odp = zapisz(client, [{'typ': 'kpi', 'wymiar': None}])
    assert odp.status_code == 200
    assert odp.get_json()['zapisano'] is True
    assert odp.get_json()['kafelkow'] == 1


def test_zapis_tworzy_wiersz_w_bazie(client, uzytkownik):
    zapisz(client, [{'typ': 'kpi', 'wymiar': None}])
    assert UkladDashboardu.query.filter_by(user_id=uzytkownik.id).count() == 1


def test_pusty_uklad_wolno_zapisac(client):
    assert zapisz(client, []).status_code == 200


def test_zapis_nieznanego_typu_oddaje_400_z_komunikatem_po_polsku(client):
    odp = zapisz(client, [{'typ': 'wykres-slonca'}])
    assert odp.status_code == 400
    tresc = odp.get_json()
    assert tresc['error'] == 'zly_uklad'
    assert 'wykres-slonca' in tresc['komunikat']


def test_zapis_ponad_limit_oddaje_400(client):
    pozycje = [{'typ': TYP_WYMIAROWY, 'wymiar': WYMIAR}] * (MAKS_KAFELKOW + 1)
    odp = zapisz(client, pozycje)
    assert odp.status_code == 400
    assert str(MAKS_KAFELKOW) in odp.get_json()['komunikat']


def test_zapis_bez_ciala_oddaje_400_a_nie_500(client):
    odp = client.post('/reports/api/uklad', data='nie-json',
                      content_type='application/json')
    assert odp.status_code == 400


def test_zapis_bez_sesji_oddaje_401_w_json(app):
    odp = app.test_client().post('/reports/api/uklad', json={'uklad': []})
    assert odp.status_code == 401
    assert odp.get_json()['error'] == 'unauthorized'


def test_zapis_nie_przyjmuje_metody_get(client):
    assert client.get('/reports/api/uklad').status_code == 405


def test_odrzucony_zapis_nie_rusza_zapisanego_ukladu(client, uzytkownik):
    """Dopisane ponad plan: zły układ ma się odbić, ZANIM cokolwiek dotknie
    bazy — inaczej nieudany zapis zostawiałby pół-układ."""
    zapisz(client, [{'typ': 'kpi', 'wymiar': None}])
    zapisz(client, [{'typ': 'wykres-slonca'}])
    wiersz = UkladDashboardu.query.filter_by(user_id=uzytkownik.id).first()
    assert wiersz.uklad == [{'typ': 'kpi', 'wymiar': None}]


# --- użytkownik zniknął między dekoratorem a trasą --------------------------
# Uwaga dyspozytora z przeglądu partii A: `_zalogowany()` szuka użytkownika po
# e-mailu z sesji i może zwrócić None (konto usunięte po zalogowaniu).
# `zapisz_uklad(None)` i `przywroc_domyslny(None)` rzuciłyby AttributeError,
# czyli 500 — trasa ma odpowiedzieć 401 z komunikatem, zanim dotknie serwisu.

def _bez_uzytkownika(monkeypatch):
    import modules.reports.routers_analiza as trasy
    monkeypatch.setattr(trasy, '_zalogowany', lambda: None)


def test_zapis_bez_uzytkownika_w_bazie_oddaje_401_a_nie_500(client, monkeypatch):
    _bez_uzytkownika(monkeypatch)
    odp = zapisz(client, [{'typ': 'kpi', 'wymiar': None}])
    assert odp.status_code == 401
    assert odp.get_json()['error'] == 'unauthorized'
    assert 'zaloguj' in odp.get_json()['komunikat'].lower()
    assert UkladDashboardu.query.count() == 0


def test_przywrocenie_bez_uzytkownika_w_bazie_oddaje_401_a_nie_500(client, monkeypatch):
    _bez_uzytkownika(monkeypatch)
    odp = client.post('/reports/api/uklad/domyslny', json={})
    assert odp.status_code == 401
    assert odp.get_json()['error'] == 'unauthorized'
    assert odp.get_json()['komunikat']


# --- przywrócenie domyślnego ------------------------------------------------

def test_przywrocenie_domyslnego_kasuje_wiersz(client, uzytkownik):
    zapisz(client, [{'typ': 'kpi', 'wymiar': None}])
    odp = client.post('/reports/api/uklad/domyslny', json={})
    assert odp.status_code == 200
    assert odp.get_json()['przywrocono'] is True
    assert UkladDashboardu.query.filter_by(user_id=uzytkownik.id).count() == 0


def test_przywrocenie_bez_wiersza_oddaje_200_i_false(client):
    odp = client.post('/reports/api/uklad/domyslny', json={})
    assert odp.status_code == 200
    assert odp.get_json()['przywrocono'] is False


def test_przywrocenie_bez_sesji_oddaje_401(app):
    assert app.test_client().post('/reports/api/uklad/domyslny', json={}).status_code == 401


# --- żądania zmieniające układ muszą być JSON-em (przegląd gałęzi, D4) -------
# Formularz z obcej strony NIE ustawi `Content-Type: application/json` bez
# zapytania wstępnego CORS, na które ten serwer nie odpowiada zgodą. Wymóg
# JSON-a zamyka więc drogę „cudza strona kasuje komuś prywatny układ" także
# wtedy, gdy przeglądarka dołączyłaby ciasteczko `remember_token`.

@pytest.mark.parametrize('rodzaj', [
    {},                                                    # bez ciała i bez nagłówka
    {'data': 'x=1', 'content_type': 'application/x-www-form-urlencoded'},
    {'data': 'x', 'content_type': 'text/plain'},
    {'data': '', 'content_type': 'multipart/form-data; boundary=x'},
])
def test_przywrocenie_bez_json_oddaje_400_i_niczego_nie_kasuje(client, uzytkownik, rodzaj):
    zapisz(client, [{'typ': 'kpi', 'wymiar': None}])
    odp = client.post('/reports/api/uklad/domyslny', **rodzaj)
    assert odp.status_code == 400
    tresc = odp.get_json()
    assert tresc['error'] == 'zle_zadanie'
    assert 'JSON' in tresc['komunikat']
    assert UkladDashboardu.query.filter_by(user_id=uzytkownik.id).count() == 1


@pytest.mark.parametrize('rodzaj', [
    {'data': 'uklad=%5B%5D', 'content_type': 'application/x-www-form-urlencoded'},
    {'data': '{"uklad": []}', 'content_type': 'text/plain'},
])
def test_zapis_bez_json_oddaje_400_i_niczego_nie_zapisuje(client, uzytkownik, rodzaj):
    """`/api/uklad` odrzucał nie-JSON już wcześniej (`get_json(silent=True)`
    daje wtedy None) — test pilnuje, żeby tak zostało. Ciało `text/plain`
    z poprawnym JSON-em w środku to dokładnie to, co wyśle formularz
    z obcej strony z `enctype="text/plain"`."""
    odp = client.post('/reports/api/uklad', **rodzaj)
    assert odp.status_code == 400
    assert UkladDashboardu.query.filter_by(user_id=uzytkownik.id).count() == 0


# --- pole traci wymiar=True po zapisaniu układu (przegląd gałęzi, M7) -------

def test_analytics_z_polem_ktore_stracilo_wymiar_oddaje_200_i_liczy_pominiety(
        client, uzytkownik, monkeypatch):
    """R2 planu: „pole traci wymiar=True → pozycja pominięta i policzona, nie
    kasowana". Do przeglądu gałęzi działało to dla 10 z 19 wymiarów; dla
    wymiarów z WŁASNEJ listy typu (karty kubełkowe) nieaktualna pozycja
    przechodziła odczyt i `naleznosci_wg_wymiaru` kończył się 500."""
    import dataclasses
    from modules.reports.fields import POLA
    zapisz(client, [{'typ': 'kpi', 'wymiar': None},
                    {'typ': 'naleznosci', 'wymiar': 'payment_method'}])
    monkeypatch.setitem(POLA, 'payment_method',
                        dataclasses.replace(POLA['payment_method'], wymiar=False))

    odp = client.get('/reports/api/analytics')
    assert odp.status_code == 200
    dane = odp.get_json()
    assert dane['pominietych'] == 1
    assert 'naleznosci:payment_method' not in dane['karty']
    assert dane['kpi'] is not None

    strona = client.get('/reports/analiza')
    assert strona.status_code == 200
    assert 'data-klucz="naleznosci:payment_method"' not in strona.get_data(as_text=True)
    # Wiersz w bazie NIETKNIĘTY — pole może wrócić.
    wiersz = UkladDashboardu.query.filter_by(user_id=uzytkownik.id).first()
    assert len(wiersz.uklad) == 2


# --- /api/analytics czyta układ Z BAZY --------------------------------------

def test_analytics_bez_zapisanego_ukladu_daje_karty_domyslne(client):
    dane = client.get('/reports/api/analytics').get_json()
    oczekiwane = {i.klucz for i in UKLAD_DOMYSLNY if KATALOG[i.typ].wymiarowy}
    assert set(dane['karty']) == oczekiwane


def test_analytics_idzie_za_zapisanym_ukladem(client):
    zapisz(client, [{'typ': TYP_WYMIAROWY, 'wymiar': INNY_WYMIAR}])
    dane = client.get('/reports/api/analytics').get_json()
    assert set(dane['karty']) == {f'{TYP_WYMIAROWY}:{INNY_WYMIAR}'}


def test_analytics_nie_przyjmuje_listy_kafelkow_z_adresu(client):
    """Gdyby endpoint brał układ z zapytania, limit dwudziestu kafelków dałoby
    się obejść ręcznie spreparowanym adresem — a endpoint jest osiągalny dla
    każdego, kto ma dostęp do modułu."""
    zapisz(client, [{'typ': 'kpi', 'wymiar': None}])
    dane = client.get('/reports/api/analytics?uklad=' +
                      'kanal:order_source,' * 200).get_json()
    assert dane['karty'] == {}


def test_stary_parametr_wymiaru_w_adresie_jest_ignorowany_a_nie_bledem(client):
    """Adres z zakładki sprzed Planu D ma pokazać pulpit, a nie stronę błędu."""
    odp = client.get('/reports/api/analytics?kanal=caretaker')
    assert odp.status_code == 200


def test_pusty_zapisany_uklad_daje_payload_bez_kart(client):
    zapisz(client, [])
    dane = client.get('/reports/api/analytics').get_json()
    assert dane['karty'] == {}
    assert dane['lejek'] is None


def test_payload_niesie_liczbe_pominietych(client, uzytkownik):
    db.session.add(UkladDashboardu(
        user_id=uzytkownik.id,
        uklad=[{'typ': 'kpi', 'wymiar': None},
               {'typ': 'karta-ktorej-nie-ma', 'wymiar': None}]))
    db.session.commit()
    assert client.get('/reports/api/analytics').get_json()['pominietych'] == 1


def test_uklad_jest_prywatny_takze_dla_api(app, client):
    """Dopisane ponad plan: /api/analytics drugiego użytkownika nie widzi
    układu pierwszego — użytkownik bierze się z SESJI."""
    db.session.add(User(email='drugi@woodpower.pl', password='x',
                        role='user', active=True))
    db.session.commit()
    zapisz(client, [{'typ': 'kpi', 'wymiar': None}])

    drugi = app.test_client()
    with drugi.session_transaction() as sesja:
        sesja['user_email'] = 'drugi@woodpower.pl'
    dane = drugi.get('/reports/api/analytics').get_json()
    oczekiwane = {i.klucz for i in UKLAD_DOMYSLNY if KATALOG[i.typ].wymiarowy}
    assert set(dane['karty']) == oczekiwane


# --- strona -----------------------------------------------------------------

def test_strona_renderuje_sie_z_zapisanym_ukladem(client):
    zapisz(client, [{'typ': TYP_WYMIAROWY, 'wymiar': INNY_WYMIAR}])
    odp = client.get('/reports/analiza')
    assert odp.status_code == 200
    assert f'data-klucz="{TYP_WYMIAROWY}:{INNY_WYMIAR}"' in odp.get_data(as_text=True)


def test_strona_renderuje_sie_przy_pustym_ukladzie(client):
    zapisz(client, [])
    odp = client.get('/reports/analiza')
    assert odp.status_code == 200


def test_strona_niesie_katalog_w_atrybucie_danych(client):
    strona = client.get('/reports/analiza').get_data(as_text=True)
    assert 'data-katalog=' in strona
    assert 'data-maks-kafelkow="%d"' % MAKS_KAFELKOW in strona


def test_strona_ze_starym_parametrem_wymiaru_nie_pada(client):
    assert client.get('/reports/analiza?kanal=caretaker').status_code == 200
