# -*- coding: utf-8 -*-
"""
API panelu biura priorytetów produkcji — /production/api/priorytety/* (program „Priorytety produkcji”, krok K2).

Plan: docs/superpowers/plans/2026-10-05-priorytety-krok-K2-panel-api.md. Spec: 2026-10-04-priorytety-produkcji-design.md,
sekcje 3.1–3.3, 4.4, 5.6, 7.1–7.3, 8.6, 9.4, 10.

Minimalna apka (SQLite in-memory) z samym blueprintem panelu. Dekorator dostępu do modułu podmieniony na przelotkę,
a anonimowy użytkownik udaje admina (rolę test zmienia `monkeypatch.setattr(_UzytkownikTestowy, 'role', …)`).
Prawdziwą kontrolę dostępu sprawdza fikstura `prawdziwy_dostep` (wzór tests/test_logistyka_panel_api.py).

SQLite pomija FOR UPDATE, więc kolejności blokad pilnujemy kolejnością zapytań i commitów (tests/blokady_pomocnicze.py).
„Dziś” przeliczenia rang jest zamrożone (`zamrozony_dzien`, DZIS z tests/priorytety_fixtures.py) — terminy w testach
liczymy od DZIS, nigdy stałą datą.
"""
import itertools
import os
import sys
from datetime import date, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from flask_login import AnonymousUserMixin, LoginManager
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.logistics.models import Route, RouteStop
from modules.production.models import ProductionOrder
from modules.production.priorytety.models import PriorityLog, PriorityRung
from modules.production.priorytety.services import drabina, kolejka, widok
from modules.users.models import User
from tests.blokady_pomocnicze import Zapytania, indeks_blokady_tras
from tests.logistyka_fixtures import DZIS_TESTOW, TABLES, produkt
from tests.priorytety_fixtures import (  # noqa: F401
    DZIS, czyste_ustawienia, drabina_domyslna, szpieg_utrwal, ustaw, zamrozony_dzien,
)

BASE = '/production/api/priorytety'
KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (metoda, ścieżka względem BASE) — wszystkie końcówki panelu. Lista rośnie z Taskami planu K2 i kroku K3.
KONCOWKI = [
    ('GET', '/drabina'),
    ('PUT', '/drabina/kolejnosc'),
    ('PUT', '/zamowienia/gwiazdki'),
    ('POST', '/przelicz'),
    ('GET', '/kolejka'),
    ('GET', '/zamowienia/<int:order_id>/priorytet'),
    ('GET', '/ustawienia'),
    ('PUT', '/ustawienia'),
    # krok K3: stoły i odłożenia (odczyt)
    ('GET', '/stoly'),
    ('GET', '/odlozenia'),
    # krok K3: „Wyślij na stanowisko” i „Zdejmij ze stołu” (spec 5.7)
    ('POST', '/stoly/<kod>/wyslij'),
    ('POST', '/stoly/<kod>/zdejmij'),
    # krok K3: start stołów (spec 5.8)
    ('GET', '/start'),
    ('POST', '/start/przygotuj'),
]
ETYKIETY_DOMYSLNE = ['★★★★★', 'Po terminie', '★★★★', 'Blisko terminu', 'Rozpoczęte', '★★★', '★★', '★',
                     'bez gwiazdek']
_licznik = itertools.count(1)


class _UzytkownikTestowy(AnonymousUserMixin):
    """Zalogowany „admin” bez sesji: LOGIN_DISABLED przepuszcza login_required, a admin_required czyta `role`."""
    id = 1
    email = 'biuro@woodpower.pl'
    role = 'admin'
    is_authenticated = True


@pytest.fixture()
def app(monkeypatch, zamrozony_dzien, czyste_ustawienia):
    import modules.users.decorators as decorators
    monkeypatch.setattr(decorators, 'require_module_access', lambda *a, **k: (lambda f: f))
    from modules.production.logistics.services import routes as uslugi_tras
    monkeypatch.setattr(uslugi_tras, 'dzis', lambda: DZIS_TESTOW)

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['LOGIN_DISABLED'] = True

    menedzer = LoginManager()
    menedzer.anonymous_user = _UzytkownikTestowy
    menedzer.init_app(app)

    @menedzer.user_loader
    def _zaladuj_uzytkownika(user_id):
        return User.query.get(int(user_id))

    from modules.production.priorytety import priorytety_panel_bp
    app.register_blueprint(priorytety_panel_bp, url_prefix=BASE)
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABLES)
        drabina_domyslna()
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def prawdziwy_dostep(app, monkeypatch):
    """Prawdziwy `require_module_access` i `login_required` (bez LOGIN_DISABLED)."""
    import modules.users.decorators as decorators
    from modules.users.decorators import permission_required
    monkeypatch.setattr(decorators, 'require_module_access', permission_required.require_module_access)
    app.config['LOGIN_DISABLED'] = False
    app.secret_key = 'klucz-sesji-testow-priorytetow-' + 'x' * 16
    return app


# ── Task 1: blueprint, rejestracja, kontrola dostępu ─────────────────────────────────────────────────────────

def test_zestaw_koncowek(app):
    reguly = {(metoda, r.rule[len(BASE):]) for r in app.url_map.iter_rules()
              if r.rule.startswith(BASE + '/') and not r.endpoint.endswith('.static')
              for metoda in r.methods - {'HEAD', 'OPTIONS'}}
    assert reguly == set(KONCOWKI)
    assert len(KONCOWKI) == 14


def test_blueprint_zarejestrowany_w_app():
    import ast
    with open(os.path.join(KORZEN, 'app.py'), encoding='utf-8') as f:
        drzewo = ast.parse(f.read())
    rejestracja = next(w for w in ast.walk(drzewo)
                       if isinstance(w, ast.FunctionDef) and w.name == 'register_blueprints_lazy')
    zrodlo = ast.unparse(rejestracja) if hasattr(ast, 'unparse') else ''
    assert 'from modules.production.priorytety import priorytety_panel_bp' in zrodlo
    assert "app.register_blueprint(priorytety_panel_bp, url_prefix='/production/api/priorytety')" in zrodlo


def _sciezka(sciezka):
    """Ścieżka reguły z parametrem → konkretny adres (np. `<int:order_id>` → 1)."""
    return BASE + sciezka.replace('<int:order_id>', '1').replace('<kod>', 'gluing')


@pytest.mark.parametrize('metoda, sciezka', KONCOWKI)
def test_bez_sesji_401_json(prawdziwy_dostep, metoda, sciezka):
    r = prawdziwy_dostep.test_client().open(_sciezka(sciezka), method=metoda)
    assert r.status_code == 401
    assert r.get_json() == {'error': 'unauthorized'}


@pytest.mark.parametrize('metoda, sciezka', KONCOWKI)
def test_bez_uprawnien_do_produkcji_403_json(prawdziwy_dostep, monkeypatch, metoda, sciezka):
    from modules.users.services.permission_service import PermissionService
    db.session.add(User(email='biuro@woodpower.pl', password='x', active=True))
    db.session.commit()
    monkeypatch.setattr(PermissionService, 'user_has_module_access',
                        staticmethod(lambda uid, module_key: False))
    klient = prawdziwy_dostep.test_client()
    with klient.session_transaction() as sesja:
        sesja['user_email'] = 'biuro@woodpower.pl'
    r = klient.open(_sciezka(sciezka), method=metoda)
    assert r.status_code == 403
    assert r.get_json() == {'error': 'module_access_denied'}


# ── pomocniki danych ─────────────────────────────────────────────────────────────────────────────────────────

def zam(statusy=('czeka_na_sklejanie',), gwiazdki=0, termin=None, numer=None, klient=None, **kolumny):
    """Zamówienie z jedną pozycją na każdy status; wszystkie pozycje z terminem `termin`. Commituje."""
    n = next(_licznik)
    order = ProductionOrder(baselinker_order_id=900000 + n,
                            internal_order_number=numer if numer is not None else str(5000 + n),
                            client_name=klient or 'Klient testowy %d' % n, priority_stars=gwiazdki, **kolumny)
    db.session.add(order)
    db.session.flush()
    for i, status in enumerate(statusy, start=1):
        produkt(order, status=status, sekwencja=i, deadline_date=termin)
    db.session.commit()
    return order


def trasa(nazwa='Śląsk', status='robocza', date_from=date(2026, 10, 8), zamowienia=(), szczebel=True):
    """Trasa wstawiona modelem (bez routes.utworz). `szczebel` — z wierszem drabiny w miejscu domyślnym. Commituje."""
    r = Route(name=nazwa, date_from=date_from, date_to=date_from + timedelta(days=1), status='robocza')
    db.session.add(r)
    db.session.flush()
    for i, order in enumerate(zamowienia, start=1):
        db.session.add(RouteStop(route_id=r.id, order_id=order.id, position=i))
    if szczebel:
        drabina.zapewnij_szczebel_trasy(r)
    r.status = status
    db.session.commit()
    return r


def szczebel_tagu(tag):
    return PriorityRung.query.filter_by(kind='tag', tag=tag).one()


def szczebel_trasy(route):
    return PriorityRung.query.filter_by(kind='route', route_id=route.id).one()


def kolejnosc_w_bazie():
    """Klucze szczebli po `position` — świeży odczyt (po rollbacku migawki sesji)."""
    db.session.rollback()
    return [s.klucz for s in PriorityRung.query.order_by(PriorityRung.position, PriorityRung.id).all()]


def _blad_mysql(kod, komunikat='Deadlock found when trying to get lock'):
    from sqlalchemy.exc import OperationalError
    return OperationalError('UPDATE prod_priority_rungs SET ...', {}, Exception(kod, komunikat))


def _commit_z_bledami(monkeypatch, bledy):
    """`db.session.commit`: n-te wywołanie najpierw wypycha zapisy (idą do bazy, więc rollback musi je cofnąć), potem
    rzuca `bledy[n]`; poza listą i dla None — prawdziwy commit. Zwraca listę wywołań. Każda próba zapisu panelu ma
    dwa commity (koniec migawki przed blokadą, commit zapisu), więc błąd zapisu to drugi element pary."""
    oryginal = db.session.commit
    wywolania = []

    def commit():
        numer = len(wywolania)
        wywolania.append(numer)
        if numer < len(bledy) and bledy[numer] is not None:
            db.session.flush()
            raise bledy[numer]
        return oryginal()

    monkeypatch.setattr(db.session, 'commit', commit)
    return wywolania


@pytest.fixture()
def utrwal_atrapa(monkeypatch):
    """`kolejka.utrwal` bez przeliczenia: notuje wywołania i oddaje udany raport."""
    wywolania = []

    def atrapa(*args, **kwargs):
        wywolania.append(kwargs)
        return {'success': True, 'zamowien': 0, 'pozycji': 0, 'zmienione_zamowienia': 0, 'zmienione_pozycje': 0,
                'ostrzezenia': [], 'duration_seconds': 0.0, 'error': None}
    monkeypatch.setattr(kolejka, 'utrwal', atrapa)
    return wywolania


def _porazka_utrwal(wariant):
    """Dwie postacie nieudanego przeliczenia: wyjątek albo raport `success: False` z tekstem błędu bazy."""
    def rzuca(*args, **kwargs):
        raise RuntimeError('SEKRETNY_BLAD_SQL rzucony')

    def zwraca(*args, **kwargs):
        return {'success': False, 'error': 'SEKRETNY_BLAD_SQL w raporcie'}
    return rzuca if wariant == 'rzuca' else zwraca


# ── Task 2: drabina ─────────────────────────────────────────────────────────────────────────────────────────

def test_drabina_szczeble_w_kolejnosci_z_etykietami_i_ruchomoscia(client):
    r = client.get(BASE + '/drabina')
    assert r.status_code == 200
    dane = r.get_json()
    assert dane['success'] is True and dane['uzupelniono'] == 0 and dane['ostrzezenia'] == []
    szczeble = dane['szczeble']
    assert [s['etykieta'] for s in szczeble] == ETYKIETY_DOMYSLNE
    assert [s['pozycja'] for s in szczeble] == list(range(1, 10))
    assert [s['ruchomy'] for s in szczeble] == [False, True, False, True, True, False, False, False, False]
    assert [s['rodzaj'] for s in szczeble] == ['gwiazdki', 'tag', 'gwiazdki', 'tag', 'tag', 'gwiazdki',
                                              'gwiazdki', 'gwiazdki', 'gwiazdki']
    assert szczeble[0]['gwiazdki'] == 5 and szczeble[0]['tag'] is None and szczeble[0]['trasa'] is None
    assert szczeble[1]['tag'] == 'po_terminie' and szczeble[1]['gwiazdki'] is None
    assert szczeble[8]['gwiazdki'] == 0


def test_drabina_liczniki_w_produkcji_na_zywo(client):
    zam(gwiazdki=5, termin=DZIS + timedelta(days=30))
    zam(termin=DZIS + timedelta(days=1))                        # blisko terminu, bez gwiazdek
    zam(termin=DZIS + timedelta(days=60))                       # bez gwiazdek
    zam(statusy=('spakowane',), gwiazdki=5, termin=DZIS)        # poza produkcją — nie liczy się
    na_trasie = zam(gwiazdki=5, termin=DZIS + timedelta(days=30))
    trasa(zamowienia=[na_trasie])
    # Kolumn priority_rung nikt nie ustawiał — liczniki muszą pochodzić z policz() na żywo.
    assert ProductionOrder.query.filter(ProductionOrder.priority_rung.isnot(None)).count() == 0

    szczeble = client.get(BASE + '/drabina').get_json()['szczeble']
    liczniki = {s['etykieta']: s['w_produkcji'] for s in szczeble}
    assert liczniki == {'★★★★★': 1, 'Śląsk': 1, 'Po terminie': 0, '★★★★': 0, 'Blisko terminu': 1,
                        'Rozpoczęte': 0, '★★★': 0, '★★': 0, '★': 0, 'bez gwiazdek': 1}


def test_drabina_trasa_zaladowana_niewidoczna(client):
    trasa(nazwa='Mazowsze', status='zaladowana')
    widoczna = trasa(nazwa='Śląsk', status='zatwierdzona')
    szczeble = client.get(BASE + '/drabina').get_json()['szczeble']
    trasy = [s for s in szczeble if s['rodzaj'] == 'trasa']
    assert [t['trasa']['id'] for t in trasy] == [widoczna.id]
    assert len(szczeble) == 10
    assert [s['pozycja'] for s in szczeble] == list(range(1, 11))


def test_drabina_trasa_bez_zamowien_w_produkcji_zero(client):
    r = trasa(nazwa='Śląsk', date_from=date(2026, 10, 8))
    szczeble = client.get(BASE + '/drabina').get_json()['szczeble']
    s = szczeble[1]
    assert s['rodzaj'] == 'trasa' and s['pozycja'] == 2 and s['ruchomy'] is True and s['w_produkcji'] == 0
    assert s['etykieta'] == 'Śląsk' and s['id'] == szczebel_trasy(r).id
    assert s['trasa'] == {'id': r.id, 'nazwa': 'Śląsk', 'status': 'robocza', 'date_from': '2026-10-08',
                          'date_to': '2026-10-09'}


def _szczebel_trasy_atrapa(route_id, nazwa, date_from):
    return SimpleNamespace(kind='route', route_id=route_id,
                           route=SimpleNamespace(id=route_id, name=nazwa, date_from=date_from))


def test_ostrzezenie_dat_tylko_dla_odwroconych_sasiadow():
    szczeble = [
        SimpleNamespace(kind='stars', route_id=None, route=None),
        _szczebel_trasy_atrapa(7, 'Śląsk', date(2026, 10, 8)),
        SimpleNamespace(kind='tag', route_id=None, route=None),
        _szczebel_trasy_atrapa(9, 'Pomorze', date(2026, 10, 12)),
        _szczebel_trasy_atrapa(4, 'Mazowsze', date(2026, 10, 10)),
    ]
    assert widok.ostrzezenia_dat(szczeble) == [{
        'kod': 'daty_tras', 'route_ids': [9, 4],
        'message': 'Trasa „Pomorze” (od 12.10) stoi wyżej niż „Mazowsze” (od 10.10).'}]


def test_ostrzezenie_dat_brak_gdy_zgodne():
    szczeble = [_szczebel_trasy_atrapa(1, 'A', date(2026, 10, 8)),
                SimpleNamespace(kind='stars', route_id=None, route=None),
                _szczebel_trasy_atrapa(2, 'B', date(2026, 10, 8)),
                _szczebel_trasy_atrapa(3, 'C', date(2026, 10, 9))]
    assert widok.ostrzezenia_dat(szczeble) == []


def test_drabina_pokazuje_ostrzezenie_dat(client):
    trasa(nazwa='Śląsk', date_from=date(2026, 10, 8))
    pomorze = trasa(nazwa='Pomorze', date_from=date(2026, 10, 12))
    drabina.przesun(szczebel_trasy(pomorze).id, 2)
    db.session.commit()
    ostrzezenia = client.get(BASE + '/drabina').get_json()['ostrzezenia']
    assert [o['kod'] for o in ostrzezenia] == ['daty_tras']


def _szpiedzy_samonaprawy(monkeypatch):
    from modules.production.logistics.services import routes
    znaczniki = []
    commit, blokada, uzupelnij = db.session.commit, routes.zablokuj_trasy, drabina.uzupelnij

    def szpieg_commit():
        znaczniki.append('commit')
        return commit()

    def szpieg_blokady(*a, **k):
        znaczniki.append('blokada')
        return blokada(*a, **k)

    def szpieg_uzupelnij(*a, **k):
        znaczniki.append('uzupelnij')
        return uzupelnij(*a, **k)

    monkeypatch.setattr(db.session, 'commit', szpieg_commit)
    monkeypatch.setattr(routes, 'zablokuj_trasy', szpieg_blokady)
    monkeypatch.setattr(drabina, 'uzupelnij', szpieg_uzupelnij)
    return znaczniki


def test_samonaprawa_drabiny_pod_blokada_tras(client, monkeypatch):
    r = trasa(nazwa='Bez szczebla', szczebel=False)
    znaczniki = _szpiedzy_samonaprawy(monkeypatch)

    dane = client.get(BASE + '/drabina').get_json()

    assert dane['uzupelniono'] == 1
    assert PriorityRung.query.filter_by(kind='route', route_id=r.id).count() == 1
    assert 'Bez szczebla' in [s['etykieta'] for s in dane['szczeble']]
    pierwszy_commit, pierwsza_blokada = znaczniki.index('commit'), znaczniki.index('blokada')
    indeks_uzupelnij = znaczniki.index('uzupelnij')
    assert pierwszy_commit < pierwsza_blokada < indeks_uzupelnij
    assert 'commit' in znaczniki[indeks_uzupelnij:]
    # Drabina pełna → drugi odczyt bez blokad i bez zapisów.
    del znaczniki[:]
    assert client.get(BASE + '/drabina').get_json()['uzupelniono'] == 0
    assert znaczniki == []


def test_samonaprawa_dopisuje_brakujacy_szczebel_staly(client):
    db.session.delete(szczebel_tagu('rozpoczete'))
    db.session.commit()
    dane = client.get(BASE + '/drabina').get_json()
    assert dane['uzupelniono'] == 1
    assert sorted(s['etykieta'] for s in dane['szczeble']) == sorted(ETYKIETY_DOMYSLNE)


def test_samonaprawa_nieudana_nie_psuje_odczytu(client, monkeypatch):
    trasa(nazwa='Bez szczebla', szczebel=False)

    def awaria(*a, **k):
        raise RuntimeError('awaria samonaprawy')
    monkeypatch.setattr(drabina, 'uzupelnij', awaria)

    r = client.get(BASE + '/drabina')
    assert r.status_code == 200
    dane = r.get_json()
    assert dane['uzupelniono'] == 0
    assert [o['kod'] for o in dane['ostrzezenia']] == ['samonaprawa_nieudana']
    assert 'awaria samonaprawy' not in r.get_data(as_text=True)
    assert [s['etykieta'] for s in dane['szczeble']] == ETYKIETY_DOMYSLNE


def test_blad_ma_kod_i_komunikat(client):
    r = client.put(BASE + '/drabina/kolejnosc', json='x')
    assert r.status_code == 400
    dane = r.get_json()
    assert dane['success'] is False and dane['error'] == 'dane_niepoprawne' and dane['message']


def test_przesun_tagu_zmienia_kolejnosc_i_loguje(client, szpieg_utrwal):
    rozpoczete = szczebel_tagu('rozpoczete')
    r = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': rozpoczete.id, 'pozycja': 2})
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['success'] is True and dane['przeliczenie'] == 'ok'
    assert [s['etykieta'] for s in dane['szczeble']][:3] == ['★★★★★', 'Rozpoczęte', 'Po terminie']
    logi = PriorityLog.query.filter_by(action='szczebel').all()
    assert len(logi) == 1 and logi[0].user_id == 1 and (logi[0].old_value, logi[0].new_value) == ('5', '2')
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True


def test_przesun_trasy_na_koniec_pod_bez_gwiazdek(client, utrwal_atrapa):
    r = trasa(nazwa='Śląsk')
    rung = szczebel_trasy(r)
    odp = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': rung.id, 'pozycja': 10})
    assert odp.status_code == 200
    assert [s['etykieta'] for s in odp.get_json()['szczeble']][-2:] == ['bez gwiazdek', 'Śląsk']
    assert kolejnosc_w_bazie()[-1] == ('route', r.id)


def test_przesun_szczebla_gwiazdek_400_szczebel_staly(client, utrwal_atrapa):
    gwiazdki = PriorityRung.query.filter_by(kind='stars', stars=3).one()
    r = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': gwiazdki.id, 'pozycja': 1})
    assert r.status_code == 400 and r.get_json()['error'] == 'szczebel_staly'
    assert utrwal_atrapa == []


def test_przesun_nieznanego_404(client):
    r = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': 987654, 'pozycja': 1})
    assert r.status_code == 404 and r.get_json()['error'] == 'szczebel_nieznany' and r.get_json()['message']


def test_przesun_pozycja_poza_zakresem_400(client):
    rozpoczete = szczebel_tagu('rozpoczete')
    r = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': rozpoczete.id, 'pozycja': 10})
    assert r.status_code == 400 and r.get_json()['error'] == 'pozycja_niepoprawna'


@pytest.mark.parametrize('cialo', [
    {}, {'szczebel_id': 'ID'}, {'pozycja': 2}, {'szczebel_id': True, 'pozycja': 2},
    {'szczebel_id': 'ID', 'pozycja': True}, {'szczebel_id': '5', 'pozycja': 2}, {'szczebel_id': 'ID', 'pozycja': '2'},
    {'szczebel_id': 'ID', 'pozycja': 0}, {'szczebel_id': 'ID', 'pozycja': 2.0},
    {'szczebel_id': 'ID', 'pozycja': 2, 'oczekiwane': 'x'}, {'szczebel_id': 'ID', 'pozycja': 2, 'oczekiwane': [1, True]},
    [1, 2],
], ids=lambda c: repr(c))
def test_przesun_zle_cialo_400(client, cialo):
    rung_id = szczebel_tagu('rozpoczete').id
    if isinstance(cialo, dict):
        cialo = {k: (rung_id if v == 'ID' else v) for k, v in cialo.items()}
    r = client.put(BASE + '/drabina/kolejnosc', json=cialo)
    assert r.status_code == 400
    assert r.get_json()['error'] == 'dane_niepoprawne' and r.get_json()['message']
    assert PriorityLog.query.count() == 0


def test_przesun_trasy_zaladowanej_409_trasa_nieaktywna(client, utrwal_atrapa):
    r = trasa(nazwa='Załadowana', status='zaladowana')
    przed = kolejnosc_w_bazie()
    odp = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': szczebel_trasy(r).id, 'pozycja': 1})
    assert odp.status_code == 409 and odp.get_json()['error'] == 'trasa_nieaktywna'
    assert kolejnosc_w_bazie() == przed
    assert PriorityLog.query.filter_by(action='szczebel').count() == 1     # tylko wpis z założenia szczebla
    assert utrwal_atrapa == []


def test_przesun_z_nieaktualnym_oczekiwane_409_drabina_zmieniona(client, utrwal_atrapa):
    przed = kolejnosc_w_bazie()
    widoczne = [s.id for s in PriorityRung.query.order_by(PriorityRung.position).all()]
    rozpoczete = szczebel_tagu('rozpoczete')
    r = client.put(BASE + '/drabina/kolejnosc', json={
        'szczebel_id': rozpoczete.id, 'pozycja': 2, 'oczekiwane': list(reversed(widoczne))})
    assert r.status_code == 409 and r.get_json()['error'] == 'drabina_zmieniona'
    assert kolejnosc_w_bazie() == przed
    assert PriorityLog.query.count() == 0 and utrwal_atrapa == []


def test_przesun_z_aktualnym_oczekiwane_zapisuje(client, utrwal_atrapa):
    widoczne = [s.id for s in PriorityRung.query.order_by(PriorityRung.position).all()]
    rozpoczete = szczebel_tagu('rozpoczete')
    r = client.put(BASE + '/drabina/kolejnosc', json={
        'szczebel_id': rozpoczete.id, 'pozycja': 1, 'oczekiwane': widoczne})
    assert r.status_code == 200 and kolejnosc_w_bazie()[0] == ('tag', 'rozpoczete')


def test_przesun_na_to_samo_miejsce_bez_przeliczenia(client, utrwal_atrapa):
    rozpoczete = szczebel_tagu('rozpoczete')
    r = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': rozpoczete.id, 'pozycja': 5})
    assert r.status_code == 200 and r.get_json()['przeliczenie'] == 'niepotrzebne'
    assert PriorityLog.query.count() == 0 and utrwal_atrapa == []


def test_przesun_szczebla_commit_i_blokada_tras_bez_odczytu_pomiedzy(client, utrwal_atrapa):
    from sqlalchemy import event
    rozpoczete_id = szczebel_tagu('rozpoczete').id
    db.session.commit()
    with Zapytania() as z:
        def po_commicie(sesja):
            z.lista.append(('COMMIT', None))
        event.listen(db.session, 'after_commit', po_commicie)
        try:
            r = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': rozpoczete_id, 'pozycja': 2})
        finally:
            event.remove(db.session, 'after_commit', po_commicie)
    assert r.status_code == 200
    pierwszy_commit = next(i for i, (sql, _p) in enumerate(z.lista) if sql == 'COMMIT')
    blokada = indeks_blokady_tras(z)
    assert blokada == pierwszy_commit + 1
    pierwszy_zapis = z.pierwsze(lambda sql: sql.startswith('UPDATE prod_priority_rungs'))
    assert blokada < pierwszy_zapis


def test_przesun_ponawia_raz_po_1213(client, monkeypatch, utrwal_atrapa):
    rozpoczete = szczebel_tagu('rozpoczete')
    proby = _commit_z_bledami(monkeypatch, [None, _blad_mysql(1213)])
    r = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': rozpoczete.id, 'pozycja': 2})
    assert r.status_code == 200, r.get_data()[:300]
    assert len(proby) == 4
    assert kolejnosc_w_bazie()[1] == ('tag', 'rozpoczete')
    assert PriorityLog.query.filter_by(action='szczebel').count() == 1
    assert len(utrwal_atrapa) == 1


def test_przesun_dwa_1213_to_500_bez_zapisow(client, monkeypatch, utrwal_atrapa):
    rozpoczete = szczebel_tagu('rozpoczete')
    przed = kolejnosc_w_bazie()
    proby = _commit_z_bledami(monkeypatch, [None, _blad_mysql(1213), None, _blad_mysql(1213)])
    r = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': rozpoczete.id, 'pozycja': 2})
    assert r.status_code == 500
    assert r.get_json()['error'] == 'blad_serwera' and r.get_json()['message']
    assert 'Deadlock' not in r.get_data(as_text=True)
    assert len(proby) == 4
    assert kolejnosc_w_bazie() == przed
    assert PriorityLog.query.count() == 0 and utrwal_atrapa == []


@pytest.mark.parametrize('wariant', ['rzuca', 'zwraca'])
def test_przeliczenie_nieudane_nie_cofa_przesuniecia(client, monkeypatch, wariant):
    monkeypatch.setattr(kolejka, 'utrwal', _porazka_utrwal(wariant))
    rozpoczete = szczebel_tagu('rozpoczete')
    r = client.put(BASE + '/drabina/kolejnosc', json={'szczebel_id': rozpoczete.id, 'pozycja': 2})
    assert r.status_code == 200
    assert r.get_json()['przeliczenie'] == 'nieudane'
    assert 'SEKRETNY_BLAD_SQL' not in r.get_data(as_text=True)
    assert kolejnosc_w_bazie()[1] == ('tag', 'rozpoczete')


# ── Task 3: gwiazdki hurtem i ręczne przeliczenie ───────────────────────────────────────────────────────────

def _gwiazdki_w_bazie(ids):
    db.session.rollback()
    return [db.session.get(ProductionOrder, i).priority_stars for i in ids]


def test_gwiazdki_hurtem_zapisuje_i_loguje(client, szpieg_utrwal):
    a, b = zam(), zam(gwiazdki=1)
    c = zam(gwiazdki=3)
    r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [c.id, a.id, b.id], 'gwiazdki': 3})
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane == {'success': True, 'zmienione': [a.id, b.id], 'bez_zmian': [c.id], 'nieznane': [],
                    'przeliczenie': 'ok'}
    assert _gwiazdki_w_bazie([a.id, b.id, c.id]) == [3, 3, 3]
    logi = PriorityLog.query.filter_by(action='gwiazdki').order_by(PriorityLog.order_id).all()
    assert [(l.order_id, l.old_value, l.new_value, l.user_id) for l in logi] == [
        (a.id, '0', '3', 1), (b.id, '1', '3', 1)]
    zmienione = db.session.get(ProductionOrder, a.id)
    assert zmienione.priority_stars_set_by == 1 and zmienione.priority_stars_set_at is not None
    assert db.session.get(ProductionOrder, c.id).priority_stars_set_at is None
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True


def test_gwiazdki_nieznane_zwraca_w_polu(client, utrwal_atrapa):
    a = zam()
    r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [987654, a.id, a.id], 'gwiazdki': 2})
    assert r.status_code == 200
    dane = r.get_json()
    assert dane['zmienione'] == [a.id] and dane['nieznane'] == [987654] and dane['bez_zmian'] == []


def test_gwiazdki_wszystkie_nieznane_404(client, utrwal_atrapa):
    r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [987654, 987655], 'gwiazdki': 2})
    assert r.status_code == 404
    dane = r.get_json()
    assert dane['error'] == 'zamowienie_nieznane' and dane['message'] and dane['nieznane'] == [987654, 987655]
    assert PriorityLog.query.count() == 0 and utrwal_atrapa == []


@pytest.mark.parametrize('cialo, kod', [
    ({'order_ids': ['ID'], 'gwiazdki': 6}, 'gwiazdki_niepoprawne'),
    ({'order_ids': ['ID'], 'gwiazdki': -1}, 'gwiazdki_niepoprawne'),
    ({'order_ids': ['ID'], 'gwiazdki': True}, 'gwiazdki_niepoprawne'),
    ({'order_ids': ['ID'], 'gwiazdki': '3'}, 'gwiazdki_niepoprawne'),
    ({'order_ids': ['ID'], 'gwiazdki': None}, 'gwiazdki_niepoprawne'),
    ({'order_ids': ['ID'], 'gwiazdki': 2.0}, 'gwiazdki_niepoprawne'),
    ({'order_ids': [], 'gwiazdki': 3}, 'dane_niepoprawne'),
    ({'order_ids': 'ID', 'gwiazdki': 3}, 'dane_niepoprawne'),
    ({'order_ids': ['ID', True], 'gwiazdki': 3}, 'dane_niepoprawne'),
    ({'order_ids': ['ID', '7'], 'gwiazdki': 3}, 'dane_niepoprawne'),
    ({'gwiazdki': 3}, 'dane_niepoprawne'),
    ('x', 'dane_niepoprawne'),
], ids=lambda c: repr(c))
def test_gwiazdki_walidacja_400(client, utrwal_atrapa, cialo, kod):
    a = zam()
    if isinstance(cialo, dict):
        ids = cialo.get('order_ids')
        if isinstance(ids, list):
            cialo = dict(cialo, order_ids=[a.id if i == 'ID' else i for i in ids])
        elif ids == 'ID':
            cialo = dict(cialo, order_ids=a.id)
    r = client.put(BASE + '/zamowienia/gwiazdki', json=cialo)
    assert r.status_code == 400
    assert r.get_json()['error'] == kod and r.get_json()['message']
    assert _gwiazdki_w_bazie([a.id]) == [0] and PriorityLog.query.count() == 0 and utrwal_atrapa == []


def test_gwiazdki_powyzej_limitu_hurtu_400(client, utrwal_atrapa):
    from modules.production.priorytety import stale
    r = client.put(BASE + '/zamowienia/gwiazdki',
                   json={'order_ids': list(range(1, stale.LIMIT_HURTU + 2)), 'gwiazdki': 3})
    assert r.status_code == 400
    assert r.get_json()['error'] == 'za_duzo_zamowien' and r.get_json()['limit'] == stale.LIMIT_HURTU


def _ze_znacznikiem_commitu(z):
    from sqlalchemy import event

    def po_commicie(sesja):
        z.lista.append(('COMMIT', None))
    event.listen(db.session, 'after_commit', po_commicie)
    return po_commicie


def test_gwiazdki_commit_blokada_zamowien_rosnaco_potem_zapis(client, utrwal_atrapa):
    from sqlalchemy import event
    from tests.blokady_pomocnicze import blokada_zamowien
    a, b, c = zam(), zam(), zam()
    db.session.commit()
    with Zapytania() as z:
        sluchacz = _ze_znacznikiem_commitu(z)
        try:
            r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [c.id, b.id, a.id], 'gwiazdki': 4})
        finally:
            event.remove(db.session, 'after_commit', sluchacz)
    assert r.status_code == 200
    commity = [i for i, (sql, _p) in enumerate(z.lista) if sql == 'COMMIT']
    blokada = z.pierwsze(blokada_zamowien)
    zapis = z.pierwsze(lambda sql: sql.startswith('UPDATE prod_orders'))
    assert commity[0] < blokada < zapis < commity[1]
    assert blokada == commity[0] + 1                       # między commitem a blokadą żadnego SELECT-a
    assert list(z.lista[blokada][1]) == [a.id, b.id, c.id]


def test_gwiazdki_bez_blokady_tras(client, utrwal_atrapa):
    from modules.production.logistics.services.routes import KLUCZ_BLOKADY
    a = zam()
    with Zapytania() as z:
        r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [a.id], 'gwiazdki': 4})
    assert r.status_code == 200
    assert not any(KLUCZ_BLOKADY in tuple(p or ()) for _sql, p in z.lista)


def test_gwiazdki_utrwal_po_commicie(client, monkeypatch):
    a, b = zam(), zam(gwiazdki=2)
    commity = []
    oryginal_commit = db.session.commit

    def licz_commit():
        commity.append(1)
        return oryginal_commit()
    monkeypatch.setattr(db.session, 'commit', licz_commit)
    wywolania = []
    monkeypatch.setattr(kolejka, 'utrwal', lambda *a_, **k: wywolania.append(len(commity)) or {'success': True})

    r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [a.id, b.id], 'gwiazdki': 2})
    assert r.status_code == 200 and r.get_json()['przeliczenie'] == 'ok'
    assert wywolania == [2]

    # Wszystkie bez zmian → bez przeliczenia.
    del wywolania[:]
    r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [a.id, b.id], 'gwiazdki': 2})
    assert r.get_json()['przeliczenie'] == 'niepotrzebne' and wywolania == []


def test_gwiazdki_ponawia_raz_po_1213(client, monkeypatch, utrwal_atrapa):
    a = zam()
    proby = _commit_z_bledami(monkeypatch, [None, _blad_mysql(1213)])
    r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [a.id], 'gwiazdki': 5})
    assert r.status_code == 200, r.get_data()[:300]
    assert len(proby) == 4 and r.get_json()['zmienione'] == [a.id]
    assert _gwiazdki_w_bazie([a.id]) == [5]
    assert PriorityLog.query.filter_by(action='gwiazdki').count() == 1


def test_gwiazdki_dwa_1213_to_500_bez_zapisow(client, monkeypatch, utrwal_atrapa):
    a = zam(gwiazdki=1)
    proby = _commit_z_bledami(monkeypatch, [None, _blad_mysql(1213), None, _blad_mysql(1213)])
    r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [a.id], 'gwiazdki': 5})
    assert r.status_code == 500 and r.get_json()['error'] == 'blad_serwera'
    assert 'Deadlock' not in r.get_data(as_text=True)
    assert len(proby) == 4
    db.session.rollback()
    zamowienie = db.session.get(ProductionOrder, a.id)
    assert (zamowienie.priority_stars, zamowienie.priority_stars_set_at, zamowienie.priority_stars_set_by) == (
        1, None, None)
    assert PriorityLog.query.count() == 0 and utrwal_atrapa == []


def test_gwiazdki_inny_kod_bez_ponowienia(client, monkeypatch, utrwal_atrapa):
    a = zam()
    proby = _commit_z_bledami(monkeypatch, [None, _blad_mysql(1205, 'Lock wait timeout exceeded')])
    r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [a.id], 'gwiazdki': 5})
    assert r.status_code == 500 and r.get_json()['error'] == 'blad_serwera'
    assert len(proby) == 2
    assert _gwiazdki_w_bazie([a.id]) == [0]


@pytest.mark.parametrize('wariant', ['rzuca', 'zwraca'])
def test_przeliczenie_nieudane_nie_cofa_gwiazdek(client, monkeypatch, wariant):
    monkeypatch.setattr(kolejka, 'utrwal', _porazka_utrwal(wariant))
    a = zam()
    r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [a.id], 'gwiazdki': 4})
    assert r.status_code == 200 and r.get_json()['przeliczenie'] == 'nieudane'
    assert 'SEKRETNY_BLAD_SQL' not in r.get_data(as_text=True)
    assert _gwiazdki_w_bazie([a.id]) == [4]


def test_gwiazdki_zmieniaja_kolejnosc_w_kolejce(client):
    pierwsze = zam(termin=DZIS + timedelta(days=40))
    drugie = zam(termin=DZIS + timedelta(days=50))
    kolejka.utrwal()
    db.session.rollback()
    assert db.session.get(ProductionOrder, pierwsze.id).priority_rank == 1

    r = client.put(BASE + '/zamowienia/gwiazdki', json={'order_ids': [drugie.id], 'gwiazdki': 5})
    assert r.status_code == 200 and r.get_json()['przeliczenie'] == 'ok'
    db.session.rollback()
    assert db.session.get(ProductionOrder, drugie.id).priority_rank == 1
    assert db.session.get(ProductionOrder, pierwsze.id).priority_rank == 2


def test_przelicz_admin_zwraca_raport_i_loguje(client):
    zam(gwiazdki=2, termin=DZIS + timedelta(days=20))
    zam(termin=DZIS + timedelta(days=30))
    r = client.post(BASE + '/przelicz')
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['success'] is True
    assert dane['raport']['success'] is True and dane['raport']['zmienione_zamowienia'] == 2
    assert 'error' not in dane['raport']
    db.session.rollback()
    logi = PriorityLog.query.filter_by(action='przeliczenie').all()
    assert [(l.user_id, l.note, l.new_value) for l in logi] == [(1, 'panel', '2')]


@pytest.mark.parametrize('wariant', ['rzuca', 'zwraca'])
def test_przelicz_porazka_500(client, monkeypatch, wariant):
    monkeypatch.setattr(kolejka, 'utrwal', _porazka_utrwal(wariant))
    r = client.post(BASE + '/przelicz')
    assert r.status_code == 500
    assert r.get_json()['error'] == 'przeliczenie_nieudane' and r.get_json()['message']
    assert 'SEKRETNY_BLAD_SQL' not in r.get_data(as_text=True)
    assert PriorityLog.query.count() == 0


# ── Task 4: kolejka i dane modalu (tylko odczyt) ────────────────────────────────────────────────────────────

def konfiguracja(gatunek='dąb', klasa='A/B'):
    from modules.production.models import ProductionConfiguration
    cfg = ProductionConfiguration.query.filter_by(species=gatunek, technology='lity', wood_class=klasa).first()
    if cfg is None:
        cfg = ProductionConfiguration(species=gatunek, technology='lity', wood_class=klasa)
        db.session.add(cfg)
        db.session.commit()
    return cfg


def zam_z_pozycjami(pozycje, gwiazdki=0, termin=None, numer=None, **kolumny):
    """Zamówienie z pozycjami `[(status, (dlugosc, szerokosc, grubosc)), ...]` z jednej konfiguracji. Commituje."""
    cfg = konfiguracja()
    n = next(_licznik)
    order = ProductionOrder(baselinker_order_id=900000 + n,
                            internal_order_number=numer if numer is not None else str(5000 + n),
                            client_name='Klient testowy %d' % n, priority_stars=gwiazdki, **kolumny)
    db.session.add(order)
    db.session.flush()
    for i, (status, (dlugosc, szerokosc, grubosc)) in enumerate(pozycje, start=1):
        produkt(order, status=status, sekwencja=i, deadline_date=termin, configuration_id=cfg.id,
                parsed_length_cm=dlugosc, parsed_width_cm=szerokosc, parsed_thickness_cm=grubosc)
    db.session.commit()
    return order


def ids_pozycji(order):
    db.session.rollback()
    return [p.id for p in sorted(db.session.get(ProductionOrder, order.id).products,
                                 key=lambda p: p.product_sequence_in_order)]


def na_stole(station, order, product_id=None, odlozony=False, **kolumny):
    from datetime import datetime
    from modules.production.priorytety.models import StationDesk
    wiersz = StationDesk(station_code=station, order_id=order.id, product_id=product_id,
                         unit_key=('p:%d' % product_id) if product_id else ('o:%d' % order.id),
                         postponed_at=datetime(2026, 10, 5, 9, 40) if odlozony else None, **kolumny)
    db.session.add(wiersz)
    db.session.commit()
    return wiersz


def ustaw_drabine(klucze):
    """Pozycje szczebli dokładnie w kolejności `klucze` (klucz szczebla: ('stars', n) | ('tag', t) | ('route', id))."""
    szczeble = {s.klucz: s for s in PriorityRung.query.all()}
    for pozycja, klucz in enumerate(klucze, start=1):
        szczeble[klucz].position = pozycja
    db.session.commit()


def test_kolejka_przyklad_3_3_ze_specu(client):
    a = zam(gwiazdki=2, termin=DZIS + timedelta(days=12), numer='A')
    b = zam(gwiazdki=0, termin=DZIS + timedelta(days=16), numer='B')
    c = zam(gwiazdki=5, termin=DZIS + timedelta(days=15), numer='C')
    h = zam(gwiazdki=1, termin=DZIS - timedelta(days=3), numer='H')             # po terminie
    d = zam(gwiazdki=4, termin=DZIS + timedelta(days=19), numer='D')
    e = zam(gwiazdki=3, termin=DZIS + timedelta(days=1), numer='E')             # blisko terminu (3 dni robocze)
    f = zam(gwiazdki=5, termin=DZIS + timedelta(days=22), numer='F')
    g = zam(gwiazdki=0, termin=DZIS + timedelta(days=22), numer='G')
    slask = trasa(nazwa='Śląsk', zamowienia=[a, b])
    mazowsze = trasa(nazwa='Mazowsze', zamowienia=[d])
    pomorze = trasa(nazwa='Pomorze', zamowienia=[f])
    ustaw_drabine([('route', slask.id), ('stars', 5), ('tag', 'po_terminie'), ('stars', 4), ('route', mazowsze.id),
                   ('tag', 'blisko_terminu'), ('stars', 3), ('route', pomorze.id), ('stars', 2), ('stars', 1),
                   ('stars', 0), ('tag', 'rozpoczete')])

    r = client.get(BASE + '/kolejka')
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['success'] is True and dane['lacznie'] == 8 and dane['wyliczono']
    zamowienia = dane['zamowienia']
    assert [z['numer'] for z in zamowienia] == ['A', 'B', 'C', 'H', 'D', 'E', 'F', 'G']
    assert [z['ranga'] for z in zamowienia] == list(range(1, 9))
    wiersz_f = zamowienia[6]
    assert wiersz_f['order_id'] == f.id and wiersz_f['gwiazdki'] == 5
    assert wiersz_f['szczebel'] == {'id': szczebel_trasy(pomorze).id, 'rodzaj': 'trasa', 'etykieta': 'Pomorze',
                                    'pozycja': 8}
    assert wiersz_f['trasa'] == {'id': pomorze.id, 'nazwa': 'Pomorze', 'date_from': '2026-10-08'}
    assert zamowienia[3]['szczebel']['etykieta'] == 'Po terminie' and zamowienia[3]['tagi'] == ['po_terminie']
    assert zamowienia[5]['szczebel']['etykieta'] == 'Blisko terminu'
    assert zamowienia[0]['klient'] == a.client_name and zamowienia[0]['trasa']['nazwa'] == 'Śląsk'
    assert e.id and g.id and c.id and h.id   # wszystkie zamówienia w wyniku (lacznie == 8)


def test_kolejka_tagi_i_termin(client):
    po = zam(termin=DZIS - timedelta(days=1))
    blisko = zam(termin=DZIS + timedelta(days=2))
    zaczete = zam(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'), termin=DZIS + timedelta(days=30))
    daleko = zam(termin=DZIS + timedelta(days=40))
    bez_terminu = zam(termin=None)
    zamowienia = {z['order_id']: z for z in client.get(BASE + '/kolejka').get_json()['zamowienia']}
    assert zamowienia[po.id]['tagi'] == ['po_terminie']
    assert zamowienia[po.id]['termin'] == (DZIS - timedelta(days=1)).isoformat()
    assert zamowienia[blisko.id]['tagi'] == ['blisko_terminu']
    assert zamowienia[zaczete.id]['tagi'] == ['rozpoczete']
    assert zamowienia[zaczete.id]['szczebel']['etykieta'] == 'Rozpoczęte'
    assert zamowienia[bez_terminu.id]['termin'] is None and zamowienia[bez_terminu.id]['tagi'] == []
    # W szczeblu „bez gwiazdek” zamówienie bez terminu idzie na koniec.
    assert zamowienia[daleko.id]['ranga'] < zamowienia[bez_terminu.id]['ranga']
    assert zamowienia[bez_terminu.id]['ranga'] == len(zamowienia)


def test_kolejka_pomija_nieaktywne(client):
    aktywne = zam()
    for statusy in (('wstrzymane',), ('anulowane',), ('spakowane',)):
        zam(statusy=statusy)
    dane = client.get(BASE + '/kolejka').get_json()
    assert dane['lacznie'] == 1 and [z['order_id'] for z in dane['zamowienia']] == [aktywne.id]


def test_kolejka_etapy_pozycji(client):
    zam(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie', 'czeka_na_formatowanie', 'spakowane', 'anulowane'))
    (wiersz,) = client.get(BASE + '/kolejka').get_json()['zamowienia']
    assert wiersz['etapy'] == {'gluing': 2, 'formatting': 1}
    assert wiersz['pozycji'] == 3


def _przyklad_x_y():
    """Przykład X/Y ze specu 5.6: X rozpoczęte (pierwsza pozycja na Formatowaniu), Y nie."""
    x = zam_z_pozycjami([('czeka_na_formatowanie', (190, 50, 4)), ('czeka_na_sklejanie', (180, 70, 4)),
                         ('czeka_na_sklejanie', (180, 60, 3)), ('czeka_na_sklejanie', (170, 78, 3))],
                        termin=DZIS + timedelta(days=20))
    y = zam_z_pozycjami([('czeka_na_sklejanie', (200, 60, 4)), ('czeka_na_sklejanie', (150, 60, 4)),
                         ('czeka_na_sklejanie', (120, 60, 4))], termin=DZIS + timedelta(days=20))
    return x, y


def test_kolejka_stanowiska_z_kandydatow_k1(client, monkeypatch):
    x, y = _przyklad_x_y()
    kolejka.utrwal()                    # kolumny priority_rung/priority_rank (Doprecyzowania p. 13)
    oryginal = kolejka.kandydaci_stanowiska
    wywolania = []

    def szpieg(stanowisko, pozycje, statusy_zamowien, szczebel_rozpoczete=None, jednostka=None, omijajace=None):
        wynik = oryginal(stanowisko, pozycje, statusy_zamowien, szczebel_rozpoczete=szczebel_rozpoczete,
                         jednostka=jednostka, omijajace=omijajace)
        wywolania.append({'stanowisko': stanowisko, 'statusy': {p.status for p in pozycje},
                          'szczebel_rozpoczete': szczebel_rozpoczete, 'jednostka': jednostka, 'kafle': wynik.kafle,
                          'omijajace': omijajace})
        return wynik
    monkeypatch.setattr(kolejka, 'kandydaci_stanowiska', szpieg)

    r = client.get(BASE + '/kolejka?stanowisko=gluing')
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    (wywolanie,) = wywolania
    assert wywolanie['stanowisko'] == 'gluing' and wywolanie['statusy'] == {'czeka_na_sklejanie'}
    assert wywolanie['szczebel_rozpoczete'] == drabina.pozycja_tagu('rozpoczete') == 5
    assert wywolanie['jednostka'] == 'pozycja'
    assert wywolanie['omijajace'] == frozenset()        # K3-poprawka-1: Sklejania nie omija żadna pozycja
    assert [k['product_id'] for k in dane['kafle']] == wywolanie['kafle']
    px, py = ids_pozycji(x), ids_pozycji(y)
    assert wywolanie['kafle'] == [px[1], px[2], px[3], py[0], py[1], py[2]]
    assert dane['stanowisko'] == 'gluing' and dane['nazwa'] == 'Sklejanie' and dane['jednostka'] == 'pozycja'
    assert dane['lacznie'] == 6 and dane['niekompletne'] == []
    kafel = dane['kafle'][0]
    assert kafel['rozpoczete'] is True and kafel['dorobka'] is False and kafel['order_id'] == x.id
    assert kafel['szczebel']['etykieta'] == 'Rozpoczęte'
    assert kafel['material'] == {'gatunek': 'dąb', 'klasa': 'A/B', 'grubosc_cm': 4.0}
    assert kafel['wymiary'] == {'dlugosc_cm': 180.0, 'szerokosc_cm': 70.0, 'grubosc_cm': 4.0}
    assert kafel['termin'] == (DZIS + timedelta(days=20)).isoformat()
    assert dane['kafle'][3]['rozpoczete'] is False and dane['kafle'][3]['szczebel']['etykieta'] == 'bez gwiazdek'


def test_kolejka_stanowiska_czyta_szczebel_z_kolumn(client):
    piec = zam(gwiazdki=5, termin=DZIS + timedelta(days=20))
    zero = zam(gwiazdki=0, termin=DZIS + timedelta(days=20))
    # Kolumny odwrotnie niż wynikałoby z policz() (bez utrwal): stół i podgląd czytają kolumny.
    piec.priority_rung, piec.priority_rank = 9, 2
    zero.priority_rung, zero.priority_rank = 1, 1
    db.session.commit()

    stanowisko = client.get(BASE + '/kolejka?stanowisko=gluing').get_json()
    assert [k['order_id'] for k in stanowisko['kafle']] == [zero.id, piec.id]
    calosc = client.get(BASE + '/kolejka').get_json()
    assert [z['order_id'] for z in calosc['zamowienia']] == [piec.id, zero.id]


def test_kolejka_stanowiska_pomija_kafle_na_stole(client):
    lezy, odlozony, wolny = zam(), zam(), zam()
    na_stole('gluing', lezy, ids_pozycji(lezy)[0])
    na_stole('gluing', odlozony, ids_pozycji(odlozony)[0], odlozony=True, postpone_reason='brak_materialu')
    dane = client.get(BASE + '/kolejka?stanowisko=gluing').get_json()
    assert [k['order_id'] for k in dane['kafle']] == [wolny.id] and dane['lacznie'] == 1


def test_kolejka_formatowania_dzieli_na_kompletne_i_niekompletne(client):
    kompletne = zam(statusy=('czeka_na_formatowanie', 'czeka_na_krawedzie'), termin=DZIS + timedelta(days=20))
    niekompletne = zam(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'), termin=DZIS + timedelta(days=20))
    dane = client.get(BASE + '/kolejka?stanowisko=formatting').get_json()
    assert dane['jednostka'] == 'zamowienie'
    assert [k['order_id'] for k in dane['kafle']] == [kompletne.id]
    kafel = dane['kafle'][0]
    assert kafel['pozycji'] == 2 and kafel['numer'] == kompletne.internal_order_number
    assert set(kafel) == {'order_id', 'numer', 'gwiazdki', 'szczebel', 'termin', 'pozycji',
                          'sposob_dostawy_ustawiony'}
    (wiersz,) = dane['niekompletne']
    brakujaca = next(p for p in db.session.get(ProductionOrder, niekompletne.id).products
                     if p.current_status == 'czeka_na_sklejanie')
    assert wiersz == {'order_id': niekompletne.id, 'numer': niekompletne.internal_order_number,
                      'na_stanowisku': 1, 'pozycji': 2,
                      'brakuje': [{'short_id': brakujaca.short_product_id, 'stanowisko': 'gluing'}]}


def test_kolejka_formatowania_pomija_pozycje_omijajaca(client):
    """K3-poprawka-1 (spec 5.6 p. 2): pozycja bez docięcia stojąca przed Formatowaniem nie trzyma zamówienia
    w „Niekompletnych” i nie liczy się do `pozycji`; na Pakowaniu liczy się jak każda."""
    order = zam(statusy=('czeka_na_formatowanie',))
    produkt(order, status='czeka_na_sklejanie', sekwencja=2, cut_to_size=False)
    db.session.commit()

    dane = client.get(BASE + '/kolejka?stanowisko=formatting').get_json()
    assert [(k['order_id'], k['pozycji']) for k in dane['kafle']] == [(order.id, 1)]
    assert dane['niekompletne'] == []
    modal = client.get(BASE + '/zamowienia/%d/priorytet' % order.id).get_json()
    formatowanie = next(st for st in modal['stanowiska'] if st['stanowisko'] == 'formatting')
    assert formatowanie['niekompletne'] is False and formatowanie['w_kolejce'] == {'miejsce': 1, 'z': 1}

    pakowane = zam(statusy=('czeka_na_pakowanie',))
    produkt(pakowane, status='czeka_na_sklejanie', sekwencja=2, cut_to_size=False)
    db.session.commit()
    dane = client.get(BASE + '/kolejka?stanowisko=packaging').get_json()
    assert dane['kafle'] == []
    assert [(w['order_id'], w['na_stanowisku'], w['pozycji']) for w in dane['niekompletne']] == [(pakowane.id, 1, 2)]


def test_kolejka_stanowiska_niekompletne_brakuje_short_id(client):
    x = zam(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie', 'czeka_na_sklejanie', 'czeka_na_sklejanie'))
    pozycje = sorted(db.session.get(ProductionOrder, x.id).products, key=lambda p: p.id)
    dane = client.get(BASE + '/kolejka?stanowisko=formatting').get_json()
    assert dane['kafle'] == []
    (wiersz,) = dane['niekompletne']
    assert wiersz['order_id'] == x.id and wiersz['na_stanowisku'] == 1 and wiersz['pozycji'] == 4
    assert wiersz['brakuje'] == [{'short_id': p.short_product_id, 'stanowisko': 'gluing'} for p in pozycje[1:]]


def test_wejscie_kandydatow_ksztalt_i_zero_zapytan(app):
    from sqlalchemy.orm import selectinload
    from modules.production.models import ProductionProduct
    a = zam_z_pozycjami([('czeka_na_sklejanie', (100, 50, 4)), ('czeka_na_formatowanie', (90, 50, 4)),
                         ('czeka_na_sklejanie', (80, 50, 3))], gwiazdki=3, termin=DZIS + timedelta(days=9))
    b = zam_z_pozycjami([('czeka_na_sklejanie', (100, 50, 4))])
    trasa(zamowienia=[b])
    a_ids, b_ids = ids_pozycji(a), ids_pozycji(b)
    db.session.rollback()
    zamowienia = (ProductionOrder.query.options(
        selectinload(ProductionOrder.products).selectinload(ProductionProduct.configuration))
        .filter(ProductionOrder.id.in_([a.id, b.id])).order_by(ProductionOrder.id).all())
    pozycje = [p for z in zamowienia for p in z.products]
    a_id, b_id = zamowienia[0].id, zamowienia[1].id
    desk = {'p:%d' % a_ids[2], 'o:999'}
    trasy = {b_id: 77}

    with Zapytania() as z:
        wynik, statusy = widok.wejscie_kandydatow('gluing', zamowienia, pozycje, trasy, desk)
    assert z.lista == []

    assert [p.id for p in wynik] == [a_ids[0], b_ids[0]]
    assert statusy == {a.id: ((a_ids[0], 'czeka_na_sklejanie'), (a_ids[1], 'czeka_na_formatowanie'),
                              (a_ids[2], 'czeka_na_sklejanie')),
                       b.id: ((b_ids[0], 'czeka_na_sklejanie'),)}
    pierwsza = wynik[0]
    assert isinstance(pierwsza, kolejka.PozycjaStanowiska)
    assert (pierwsza.order_id, pierwsza.status, pierwsza.gatunek, pierwsza.klasa, pierwsza.gwiazdki,
            pierwsza.termin, pierwsza.na_trasie, pierwsza.dorobka) == (
        a.id, 'czeka_na_sklejanie', 'dąb', 'A/B', 3, DZIS + timedelta(days=9), False, False)
    assert float(pierwsza.dlugosc) == 100 and float(pierwsza.grubosc) == 4
    assert wynik[1].na_trasie is True
    # Klucz kafla-zamówienia też ukrywa pozycje tego zamówienia.
    wynik, _statusy = widok.wejscie_kandydatow('gluing', zamowienia, pozycje, {}, {'o:%d' % a.id})
    assert [p.id for p in wynik] == [b_ids[0]]


def test_kolejka_stanowiska_ignoruje_wiersze_stolu_innej_jednostki(client):
    k = zam(statusy=('czeka_na_formatowanie',))
    na_stole('formatting', k, ids_pozycji(k)[0])          # wiersz po jednostce `pozycja`
    dane = client.get(BASE + '/kolejka?stanowisko=formatting').get_json()
    assert dane['jednostka'] == 'zamowienie'
    assert [kafel['order_id'] for kafel in dane['kafle']] == [k.id]


def test_kolejka_pakowania_flaga_sposobu_dostawy(client):
    from modules.production.logistics import sposoby
    ze_sposobem = zam(statusy=('czeka_na_pakowanie',), override_delivery_method=sposoby.KURIER)
    bez_sposobu = zam(statusy=('czeka_na_pakowanie',))
    dane = client.get(BASE + '/kolejka?stanowisko=packaging').get_json()
    flagi = {k['order_id']: k['sposob_dostawy_ustawiony'] for k in dane['kafle']}
    assert flagi == {ze_sposobem.id: True, bez_sposobu.id: False}


@pytest.mark.parametrize('kod', ['sawmill', 'xyz', ''])
def test_kolejka_stanowisko_nieznane_400(client, kod):
    r = client.get(BASE + '/kolejka?stanowisko=' + kod)
    assert r.status_code == 400 and r.get_json()['error'] == 'stanowisko_nieznane' and r.get_json()['message']


@pytest.mark.parametrize('limit', ['0', '501', 'abc', '-1', '2.5'])
def test_kolejka_limit_400(client, limit):
    r = client.get(BASE + '/kolejka?stanowisko=gluing&limit=' + limit)
    assert r.status_code == 400 and r.get_json()['error'] == 'dane_niepoprawne'


def test_kolejka_stanowiska_limit_przycina_kafle(client):
    for _ in range(3):
        zam()
    dane = client.get(BASE + '/kolejka?stanowisko=gluing&limit=2').get_json()
    assert len(dane['kafle']) == 2 and dane['lacznie'] == 3


def _uzytkownik_biura():
    uzytkownik = User(id=1, email='biuro@woodpower.pl', password='x', active=True, first_name='Anna',
                      last_name='Biurowa')
    db.session.add(uzytkownik)
    db.session.commit()


def test_priorytet_zamowienia_pelne_dane(client):
    from modules.production.models import ProductionWorker
    _uzytkownik_biura()
    pracownik = ProductionWorker(first_name='Adam', last_name='Nowak', is_active=True)
    db.session.add(pracownik)
    db.session.commit()
    pilne = zam(gwiazdki=5, termin=DZIS + timedelta(days=5))             # wyżej w kolejce Sklejania
    nasze = zam(statusy=('czeka_na_wyciecie', 'czeka_na_sklejanie', 'czeka_na_sklejanie'),
                termin=DZIS + timedelta(days=10))
    r_trasy = trasa(nazwa='Śląsk', zamowienia=[nasze])
    for gwiazdki in (1, 2):
        assert client.put(BASE + '/zamowienia/gwiazdki',
                          json={'order_ids': [nasze.id], 'gwiazdki': gwiazdki}).status_code == 200
    _wyciecie, sklejanie_1, sklejanie_2 = ids_pozycji(nasze)
    na_stole('gluing', nasze, sklejanie_2, odlozony=True, postpone_reason='brak_materialu',
             postpone_note='czekamy na deski', postponed_by_worker_id=pracownik.id)

    r = client.get(BASE + '/zamowienia/%d/priorytet' % nasze.id)
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['success'] is True
    assert dane['zamowienie'] == {'order_id': nasze.id, 'numer': nasze.internal_order_number,
                                  'klient': nasze.client_name}
    assert dane['gwiazdki'] == 2 and dane['aktywne'] is True and dane['ranga'] == 2
    assert dane['gwiazdki_ustawione']['kto'] == 'Anna Biurowa' and dane['gwiazdki_ustawione']['kiedy']
    assert dane['szczebel']['rodzaj'] == 'trasa' and dane['szczebel']['etykieta'] == 'Śląsk'
    assert dane['szczebel']['pozycja'] == 2 and dane['szczebel']['z'] == 10
    assert dane['trasa'] == {'id': r_trasy.id, 'nazwa': 'Śląsk', 'date_from': '2026-10-08'}
    assert dane['termin'] == (DZIS + timedelta(days=10)).isoformat() and dane['tagi'] == []

    stanowiska = {s['stanowisko']: s for s in dane['stanowiska']}
    assert set(stanowiska) == {'cutting', 'gluing'}
    sklejanie = stanowiska['gluing']
    assert sklejanie['nazwa'] == 'Sklejanie' and sklejanie['pozycji'] == 2 and sklejanie['na_stole'] == []
    nasza_pozycja = db.session.get(ProductionOrder, nasze.id)
    short = {p.id: p.short_product_id for p in nasza_pozycja.products}
    (odlozenie,) = sklejanie['odlozone']
    assert odlozenie['short_id'] == short[sklejanie_2] and odlozenie['powod'] == 'brak_materialu'
    assert odlozenie['notatka'] == 'czekamy na deski' and odlozenie['pracownik'] == 'Adam Nowak'
    assert odlozenie['kiedy'] == '2026-10-05T09:40:00'
    kolejka_sklejania = client.get(BASE + '/kolejka?stanowisko=gluing').get_json()['kafle']
    miejsce = [k['product_id'] for k in kolejka_sklejania].index(sklejanie_1) + 1
    assert sklejanie['w_kolejce'] == {'miejsce': miejsce, 'z': len(kolejka_sklejania)}
    assert miejsce == 2 and pilne.id                       # ★★★★★ stoi nad trasą (miejsce domyślne)
    assert sklejanie['niekompletne'] is False
    assert stanowiska['cutting']['w_kolejce'] == {'miejsce': 1, 'z': 1}

    historia = dane['historia']
    assert [(h['akcja'], h['stare'], h['nowe'], h['kto']) for h in historia[:2]] == [
        ('gwiazdki', '1', '2', 'Anna Biurowa'), ('gwiazdki', '0', '1', 'Anna Biurowa')]


def test_priorytet_zamowienia_niekompletne_i_na_stole(client):
    from modules.production.logistics import sposoby
    x = zam(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    k = zam(statusy=('czeka_na_pakowanie',), override_delivery_method=sposoby.KURIER)
    bez = zam(statusy=('czeka_na_pakowanie',))
    na_stole('packaging', k)
    formatowanie = {s['stanowisko']: s for s in client.get(
        BASE + '/zamowienia/%d/priorytet' % x.id).get_json()['stanowiska']}['formatting']
    assert formatowanie['niekompletne'] is True and formatowanie['w_kolejce'] is None
    pakowanie = client.get(BASE + '/zamowienia/%d/priorytet' % k.id).get_json()['stanowiska'][0]
    assert pakowanie['na_stole'] == [k.internal_order_number] and pakowanie['w_kolejce'] is None
    # Pakowanie bez sposobu dostawy jest zwykłym kandydatem (spec 5.1 po logistyce 4.6): ma miejsce w kolejce.
    pakowanie_bez = client.get(BASE + '/zamowienia/%d/priorytet' % bez.id).get_json()['stanowiska'][0]
    assert pakowanie_bez['w_kolejce'] == {'miejsce': 1, 'z': 1}


def test_priorytet_zamowienia_nieaktywnego(client):
    z = zam(statusy=('spakowane',), gwiazdki=3)
    db.session.add(PriorityLog(action='gwiazdki', order_id=z.id, old_value='0', new_value='3'))
    db.session.commit()
    dane = client.get(BASE + '/zamowienia/%d/priorytet' % z.id).get_json()
    assert dane['aktywne'] is False and dane['ranga'] is None and dane['szczebel'] is None
    assert dane['stanowiska'] == [] and dane['gwiazdki'] == 3
    assert [(h['akcja'], h['kto']) for h in dane['historia']] == [('gwiazdki', None)]


def test_priorytet_zamowienia_404(client):
    r = client.get(BASE + '/zamowienia/987654/priorytet')
    assert r.status_code == 404 and r.get_json()['error'] == 'zamowienie_nieznane' and r.get_json()['message']


def test_odczyty_nie_biora_blokad(client):
    from sqlalchemy import event
    from modules.production.logistics.services.routes import KLUCZ_BLOKADY
    z_trasy = zam()
    trasa(zamowienia=[z_trasy])
    zam(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    db.session.commit()
    for adres in ('/kolejka', '/kolejka?stanowisko=gluing', '/kolejka?stanowisko=formatting',
                  '/zamowienia/%d/priorytet' % z_trasy.id):
        with Zapytania() as z:
            sluchacz = _ze_znacznikiem_commitu(z)
            try:
                r = client.get(BASE + adres)
            finally:
                event.remove(db.session, 'after_commit', sluchacz)
        assert r.status_code == 200, adres
        assert not any(sql == 'COMMIT' for sql, _p in z.lista), adres
        assert not any(KLUCZ_BLOKADY in tuple(p or ()) for _sql, p in z.lista), adres
        assert not any(sql.startswith(('UPDATE', 'INSERT', 'DELETE')) for sql, _p in z.lista), adres
        assert not any(sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE')) for sql, _p in z.lista), adres


# ── Task 5: ustawienia (admin) ──────────────────────────────────────────────────────────────────────────────

def _wartosci_konfiguracji():
    from modules.production.models import ProductionConfig
    db.session.rollback()
    return {w.config_key: w.config_value for w in ProductionConfig.query.all()}


@pytest.fixture()
def szpieg_invalidate(monkeypatch):
    from modules.production.services import config_service
    wywolania = []
    oryginal = config_service.invalidate_config_cache

    def szpieg():
        wywolania.append(1)
        return oryginal()
    monkeypatch.setattr(config_service, 'invalidate_config_cache', szpieg)
    return wywolania


def test_ustawienia_odczyt_domyslny(client):
    r = client.get(BASE + '/ustawienia')
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['success'] is True
    # Słownik stanowisk (jsonify sortuje klucze — kolejność procesu ustala UI).
    assert set(dane['stanowiska']) == {'cutting', 'assembly', 'gluing', 'formatting', 'edges', 'painting',
                                       'packaging'}
    assert dane['stanowiska']['gluing'] == {'nazwa': 'Sklejanie', 'tryb': 'stary', 'miejsca': 2,
                                            'jednostka': 'pozycja', 'limit_odlozen': 10}
    assert dane['stanowiska']['formatting']['jednostka'] == 'zamowienie'
    assert dane['stanowiska']['packaging']['jednostka'] == 'zamowienie'
    assert (dane['blisko_terminu_dni'], dane['min_app_version_code'], dane['deadline_day_type']) == (3, 0, 'robocze')


def test_ustawienia_zapis_czesciowy_i_log(client, szpieg_invalidate, utrwal_atrapa):
    r = client.put(BASE + '/ustawienia', json={'stanowiska': {'gluing': {'miejsca': 3}},
                                                'deadline_day_type': 'kalendarzowe'})
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['zmienione'] == ['DEADLINE_DAY_TYPE', 'priorytety_stol_gluing']
    assert dane['przeliczenie'] == 'niepotrzebne' and utrwal_atrapa == []
    assert dane['stanowiska']['gluing']['miejsca'] == 3 and dane['deadline_day_type'] == 'kalendarzowe'
    wartosci = _wartosci_konfiguracji()
    assert wartosci['priorytety_stol_gluing'] == '3' and wartosci['DEADLINE_DAY_TYPE'] == 'kalendarzowe'
    logi = PriorityLog.query.filter_by(action='ustawienia').order_by(PriorityLog.note).all()
    assert [(l.note, l.old_value, l.new_value, l.user_id, l.order_id) for l in logi] == [
        ('DEADLINE_DAY_TYPE', None, 'kalendarzowe', 1, None), ('priorytety_stol_gluing', None, '3', 1, None)]
    assert szpieg_invalidate == [1]


def test_ustawienia_zapis_nadpisuje_wiersz_i_loguje_stara_wartosc(client, utrwal_atrapa):
    ustaw('priorytety_tryb_gluing', 'stary')
    ustaw('priorytety_min_app_version_code', '173', 'integer')   # stół wymaga progu wersji (K4-poprawka-1)
    r = client.put(BASE + '/ustawienia', json={'stanowiska': {'gluing': {'tryb': 'stol'}}})
    assert r.status_code == 200 and r.get_json()['zmienione'] == ['priorytety_tryb_gluing']
    (log,) = PriorityLog.query.filter_by(action='ustawienia').all()
    assert (log.old_value, log.new_value) == ('stary', 'stol')
    assert _wartosci_konfiguracji()['priorytety_tryb_gluing'] == 'stol'


def test_ustawienia_walidacja_wszystko_albo_nic(client, utrwal_atrapa):
    przed = _wartosci_konfiguracji()
    r = client.put(BASE + '/ustawienia', json={
        'stanowiska': {'gluing': {'miejsca': 3, 'jednostka': 'zamowienie', 'limit_odlozen': 99}},
        'blisko_terminu_dni': 5})
    assert r.status_code == 400
    dane = r.get_json()
    assert dane['error'] == 'ustawienie_niepoprawne' and dane['pole'] == 'stanowiska.gluing.limit_odlozen'
    assert dane['message']
    assert _wartosci_konfiguracji() == przed and PriorityLog.query.count() == 0 and utrwal_atrapa == []


@pytest.mark.parametrize('cialo, kod, pole', [
    ({'stanowiska': {'gluing': {'miejsca': 0}}}, 'ustawienie_niepoprawne', 'stanowiska.gluing.miejsca'),
    ({'stanowiska': {'gluing': {'miejsca': 6}}}, 'ustawienie_niepoprawne', 'stanowiska.gluing.miejsca'),
    ({'stanowiska': {'gluing': {'miejsca': True}}}, 'ustawienie_niepoprawne', 'stanowiska.gluing.miejsca'),
    ({'stanowiska': {'gluing': {'miejsca': '2'}}}, 'ustawienie_niepoprawne', 'stanowiska.gluing.miejsca'),
    ({'stanowiska': {'gluing': {'limit_odlozen': 0}}}, 'ustawienie_niepoprawne', 'stanowiska.gluing.limit_odlozen'),
    ({'stanowiska': {'gluing': {'limit_odlozen': 51}}}, 'ustawienie_niepoprawne',
     'stanowiska.gluing.limit_odlozen'),
    ({'stanowiska': {'gluing': {'jednostka': 'x'}}}, 'ustawienie_niepoprawne', 'stanowiska.gluing.jednostka'),
    ({'stanowiska': {'gluing': {'tryb': 'nowy'}}}, 'ustawienie_niepoprawne', 'stanowiska.gluing.tryb'),
    ({'blisko_terminu_dni': -1}, 'ustawienie_niepoprawne', 'blisko_terminu_dni'),
    ({'blisko_terminu_dni': 16}, 'ustawienie_niepoprawne', 'blisko_terminu_dni'),
    ({'blisko_terminu_dni': 3.0}, 'ustawienie_niepoprawne', 'blisko_terminu_dni'),
    ({'min_app_version_code': -1}, 'ustawienie_niepoprawne', 'min_app_version_code'),
    ({'deadline_day_type': 'x'}, 'ustawienie_niepoprawne', 'deadline_day_type'),
    ({'stanowiska': {'sawmill': {'miejsca': 2}}}, 'stanowisko_nieznane', 'stanowiska.sawmill'),
    ({'stanowiska': {'gluing': {'nazwa': 'X'}}}, 'dane_niepoprawne', 'stanowiska.gluing.nazwa'),
    ({'stanowiska': {'gluing': {'blokada': 1}}}, 'dane_niepoprawne', 'stanowiska.gluing.blokada'),
    ({'stanowiska': {'gluing': 3}}, 'dane_niepoprawne', 'stanowiska.gluing'),
    ({'stanowiska': []}, 'dane_niepoprawne', 'stanowiska'),
    ({'cos_innego': 1}, 'dane_niepoprawne', 'cos_innego'),
    ('x', 'dane_niepoprawne', None),
], ids=lambda c: repr(c))
def test_ustawienia_walidacja_400(client, cialo, kod, pole):
    r = client.put(BASE + '/ustawienia', json=cialo)
    assert r.status_code == 400
    dane = r.get_json()
    assert dane['error'] == kod and dane['message'] and dane.get('pole') == pole
    assert PriorityLog.query.count() == 0


def test_ustawienia_zmiana_progu_przelicza(client, szpieg_utrwal):
    r = client.put(BASE + '/ustawienia', json={'blisko_terminu_dni': 5})
    assert r.status_code == 200 and r.get_json()['przeliczenie'] == 'ok'
    assert r.get_json()['blisko_terminu_dni'] == 5
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True


def test_ustawienia_inne_pola_bez_przeliczenia(client, utrwal_atrapa):
    r = client.put(BASE + '/ustawienia', json={'min_app_version_code': 173,
                                                'stanowiska': {'packaging': {'tryb': 'stol', 'limit_odlozen': 5}}})
    assert r.status_code == 200 and r.get_json()['przeliczenie'] == 'niepotrzebne'
    assert utrwal_atrapa == []


def test_ustawienia_bez_zmian_nic_nie_zapisuje(client, utrwal_atrapa):
    ustaw('priorytety_stol_gluing', '2', 'integer')
    ustaw('priorytety_blisko_terminu_dni', '3', 'integer')
    r = client.put(BASE + '/ustawienia', json={'stanowiska': {'gluing': {'miejsca': 2}}, 'blisko_terminu_dni': 3})
    assert r.status_code == 200
    assert r.get_json()['zmienione'] == [] and r.get_json()['przeliczenie'] == 'niepotrzebne'
    assert PriorityLog.query.count() == 0 and utrwal_atrapa == []


def test_ustawienia_zmiana_jednostki_przy_niepustym_stole(client, utrwal_atrapa):
    from modules.production.priorytety.models import StationDesk
    lezy, odlozony = zam(), zam()
    na_stole('gluing', lezy, ids_pozycji(lezy)[0])
    na_stole('gluing', odlozony, ids_pozycji(odlozony)[0], odlozony=True, postpone_reason='inne')
    przed = sorted((w.unit_key, w.postponed_at) for w in StationDesk.query.all())

    r = client.put(BASE + '/ustawienia', json={'stanowiska': {'gluing': {'jednostka': 'zamowienie'}}})
    assert r.status_code == 200 and r.get_json()['zmienione'] == ['priorytety_jednostka_gluing']
    db.session.rollback()
    assert sorted((w.unit_key, w.postponed_at) for w in StationDesk.query.all()) == przed

    dane = client.get(BASE + '/kolejka?stanowisko=gluing').get_json()
    assert dane['jednostka'] == 'zamowienie'
    assert sorted(k['order_id'] for k in dane['kafle']) == sorted([lezy.id, odlozony.id])


def test_ustawienia_i_przelicz_tylko_admin(client, monkeypatch):
    monkeypatch.setattr(_UzytkownikTestowy, 'role', 'user')
    for metoda, sciezka in (('GET', '/ustawienia'), ('PUT', '/ustawienia'), ('POST', '/przelicz')):
        r = client.open(BASE + sciezka, method=metoda, json={'blisko_terminu_dni': 5})
        assert r.status_code == 403, sciezka
        assert r.get_json() == {'success': False, 'error': 'Brak uprawnień administratora'}
    assert client.get(BASE + '/drabina').status_code == 200
    assert PriorityLog.query.count() == 0


def test_ustawienia_czytane_bez_pamieci_podrecznej_procesu(client, utrwal_atrapa):
    from sqlalchemy import text
    from modules.production.priorytety.services import ustawienia
    ustaw('priorytety_min_app_version_code', '173', 'integer')   # stół wymaga progu wersji (K4-poprawka-1)
    assert client.put(BASE + '/ustawienia', json={'stanowiska': {'gluing': {'tryb': 'stol'}}}).status_code == 200
    assert ustawienia.tryb('gluing') == 'stol'
    # Zapis „innego workera”: surowy UPDATE, bez unieważniania pamięci podręcznej tego procesu.
    db.session.execute(text("UPDATE prod_config SET config_value = 'stary' "
                            "WHERE config_key = 'priorytety_tryb_gluing'"))
    db.session.commit()
    assert ustawienia.tryb('gluing') == 'stary'


def test_ustawienia_odczyt_nie_wypycha_pracy_wolajacego(app):
    from modules.production.models import ProductionConfig
    from modules.production.priorytety.services import ustawienia
    niezapisany = ProductionConfig(config_key='niezapisany', config_value='x')
    db.session.add(niezapisany)
    assert ustawienia.tryb('gluing') == 'stary'
    assert niezapisany in db.session.new
    db.session.rollback()


def test_ustawienia_lakiernia_nie_przyjmuje_trybu_stol(client, utrwal_atrapa):
    """Spec 10 i ustalenie 15 (decyzja Konrada 5.10, wiadomość centrali do K2): Lakiernia na stałe w trybie `stary`."""
    przed = _wartosci_konfiguracji()
    r = client.put(BASE + '/ustawienia', json={'stanowiska': {'painting': {'tryb': 'stol'},
                                                              'gluing': {'miejsca': 3}}})
    assert r.status_code == 400
    dane = r.get_json()
    assert dane['error'] == 'stanowisko_bez_stolu' and dane['pole'] == 'stanowiska.painting.tryb'
    assert 'Lakiern' in dane['message']
    assert _wartosci_konfiguracji() == przed and PriorityLog.query.count() == 0
    # Tryb `stary` dla Lakierni przechodzi (to jej jedyny tryb).
    r = client.put(BASE + '/ustawienia', json={'stanowiska': {'painting': {'tryb': 'stary'}}})
    assert r.status_code == 200


# ══ K4-poprawka-1: stół nie włącza się przy progu wersji 0 (raport K3, rozstrz. 39; dziennik, rozstrz. 18) ═════

def _odmowa_progu(r, przed):
    """400 `prog_wersji_wymagany` przy polu progu, komunikat po polsku, w bazie nic się nie zmieniło."""
    assert r.status_code == 400, r.get_data()[:300]
    dane = r.get_json()
    assert dane['success'] is False and dane['error'] == 'prog_wersji_wymagany'
    assert dane['pole'] == 'min_app_version_code'
    assert u'wersj' in dane['message'] and u'starą appkę' in dane['message']
    assert _wartosci_konfiguracji() == przed and PriorityLog.query.count() == 0


def test_stol_z_progiem_zero_w_jednym_zadaniu_odrzucony(client, utrwal_atrapa):
    przed = _wartosci_konfiguracji()
    r = client.put(BASE + '/ustawienia', json={'min_app_version_code': 0,
                                                'stanowiska': {'gluing': {'tryb': 'stol'}}})
    _odmowa_progu(r, przed)


@pytest.mark.parametrize('prog', [None, '0'], ids=['brak_wiersza', 'zero'])
def test_stol_przy_zapisanym_progu_zero_odrzucony(client, utrwal_atrapa, prog):
    """„Włącz stoły” bez wpisanego progu i zwykły zapis trybu w karcie — oba widzą próg z bazy."""
    if prog is not None:
        ustaw('priorytety_min_app_version_code', prog, 'integer')
    przed = _wartosci_konfiguracji()
    r = client.put(BASE + '/ustawienia', json={'stanowiska': {'gluing': {'tryb': 'stol'}, 'cutting': {'miejsca': 3}}})
    _odmowa_progu(r, przed)


def test_obnizenie_progu_do_zera_przy_stole_odrzucone(client, utrwal_atrapa):
    ustaw('priorytety_min_app_version_code', '173', 'integer')
    ustaw('priorytety_tryb_packaging', 'stol')
    przed = _wartosci_konfiguracji()
    r = client.put(BASE + '/ustawienia', json={'min_app_version_code': 0, 'blisko_terminu_dni': 4})
    _odmowa_progu(r, przed)


def test_stol_z_progiem_w_jednym_zadaniu_przechodzi(client, utrwal_atrapa):
    """„Włącz stoły” z wpisanym progiem: jeden zapis progu i sześciu trybów (runbook K7, krok 4)."""
    stanowiska = {kod: {'tryb': 'stol'} for kod in ('cutting', 'assembly', 'gluing', 'formatting', 'edges',
                                                     'packaging')}
    r = client.put(BASE + '/ustawienia', json={'min_app_version_code': 173, 'stanowiska': stanowiska})
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['min_app_version_code'] == 173
    assert {kod: s['tryb'] for kod, s in dane['stanowiska'].items()} == dict(
        {kod: 'stol' for kod in stanowiska}, painting='stary')


def test_stol_przy_zapisanym_progu_przechodzi(client, utrwal_atrapa):
    ustaw('priorytety_min_app_version_code', '173', 'integer')
    r = client.put(BASE + '/ustawienia', json={'stanowiska': {'gluing': {'tryb': 'stol'}}})
    assert r.status_code == 200 and r.get_json()['zmienione'] == ['priorytety_tryb_gluing']


def test_zastany_stol_przy_progu_zero_nie_blokuje_wycofania_ani_innych_zmian(client, utrwal_atrapa):
    """Stan sprzed poprawki (albo wpisany ręcznie w bazie): `stol` przy progu 0. Zapis, który kombinacji nie
    wprowadza — wycofanie stanowiska na `stary`, zmiana K, ten sam tryb jeszcze raz — przechodzi; wycofanie nie może
    czekać na próg."""
    ustaw('priorytety_tryb_gluing', 'stol')
    ustaw('priorytety_tryb_cutting', 'stol')
    r = client.put(BASE + '/ustawienia', json={'stanowiska': {'gluing': {'tryb': 'stary', 'miejsca': 3},
                                                              'cutting': {'tryb': 'stol', 'miejsca': 4}},
                                                'min_app_version_code': 0})
    assert r.status_code == 200, r.get_data()[:300]
    wartosci = _wartosci_konfiguracji()
    assert (wartosci['priorytety_tryb_gluing'], wartosci['priorytety_stol_cutting']) == ('stary', '4')
    # Kolejne stanowisko na `stol` przy tym samym progu 0 — już odmowa.
    przed = _wartosci_konfiguracji()
    PriorityLog.query.delete()
    db.session.commit()
    r = client.put(BASE + '/ustawienia', json={'stanowiska': {'edges': {'tryb': 'stol'}}})
    _odmowa_progu(r, przed)


def test_lakiernia_w_stol_w_bazie_nie_wymaga_progu(client, utrwal_atrapa):
    """Lakiernia jest zawsze `stary` (spec 5.5) — zastany wiersz `stol` w bazie nie liczy się jako stół."""
    ustaw('priorytety_min_app_version_code', '173', 'integer')
    ustaw('priorytety_tryb_painting', 'stol')
    r = client.put(BASE + '/ustawienia', json={'min_app_version_code': 0})
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['min_app_version_code'] == 0


def test_prog_wersji_odmowa_po_walidacji_pol(client, utrwal_atrapa):
    """Najpierw błędy pól (kształt odpowiedzi K2), potem reguła stanu wynikowego."""
    r = client.put(BASE + '/ustawienia', json={'min_app_version_code': -1, 'stanowiska': {'gluing': {'tryb': 'stol'}}})
    assert r.status_code == 400 and r.get_json()['error'] == 'ustawienie_niepoprawne'


def test_import_pakietu_produkcji_laduje_router_priorytetow_bez_cyklu():
    """
    Świeży interpreter, kolejność jak przy starcie aplikacji: `modules.production` importuje modele priorytetów,
    a pakiet priorytetów — router panelu. Router nie może przy tym sięgać do `modules.production.routers` (ten
    importuje `apply_security` z niedokończonego `modules.production`): cykl kończył się błędem w logu przy każdym
    starcie i pakietem ładowanym dopiero drugim importem.
    """
    import subprocess
    kod = ("import sys\n"
           "import modules.production\n"
           "print('PAKIET=%s' % ('modules.production.priorytety' in sys.modules))\n"
           "print('ROUTER=%s' % ('modules.production.priorytety.routers.panel_api' in sys.modules))\n")
    wynik = subprocess.run([sys.executable, '-c', kod], cwd=KORZEN, capture_output=True, text=True,
                           env=dict(os.environ, PYTHONPATH=KORZEN), timeout=120)
    wyjscie = wynik.stdout + wynik.stderr
    assert wynik.returncode == 0, wyjscie[-2000:]
    assert 'Nie można zaimportować modeli priorytetów' not in wyjscie
    assert 'PAKIET=True' in wynik.stdout and 'ROUTER=True' in wynik.stdout


def test_kolejka_lakierni_400_stanowisko_bez_stolu(client):
    """Lakiernia nie ma stołu (spec ustalenie 15, 3.2): jej kolejność to lista po wykończeniu, nie algorytm stołu —
    podgląd stołu dla niej nie istnieje."""
    zam(statusy=('czeka_na_lakiernie',))
    r = client.get(BASE + '/kolejka?stanowisko=painting')
    assert r.status_code == 400
    assert r.get_json()['error'] == 'stanowisko_bez_stolu' and 'Lakiern' in r.get_json()['message']


def test_priorytet_zamowienia_na_lakierni_bez_miejsca_w_kolejce(client):
    z = zam(statusy=('czeka_na_lakiernie', 'czeka_na_sklejanie'))
    stanowiska = {s['stanowisko']: s for s in client.get(
        BASE + '/zamowienia/%d/priorytet' % z.id).get_json()['stanowiska']}
    assert stanowiska['painting']['pozycji'] == 1 and stanowiska['painting']['w_kolejce'] is None
    assert stanowiska['painting']['niekompletne'] is False
    assert stanowiska['gluing']['w_kolejce'] == {'miejsce': 1, 'z': 1}


# ══ Krok K3: stoły i odłożenia dla panelu (spec 5.3, 7.2) ═══════════════════════════════════════════════════

from datetime import datetime  # noqa: E402

from modules.production.priorytety import stale  # noqa: E402
from modules.production.priorytety.models import StationDesk  # noqa: E402
from modules.production.priorytety.services import stol  # noqa: E402

T_STOL = datetime(2026, 10, 5, 8, 0)


def kafel_stolu(stanowisko, obiekt, odlozony=None, zrodlo='kolejka', pobrano=T_STOL, **kolumny):
    """Wiersz stołu dla pozycji albo zamówienia. `odlozony` — czas odłożenia (None = leży na stole). Commituje."""
    if isinstance(obiekt, ProductionOrder):
        dane = dict(order_id=obiekt.id, product_id=None, unit_key='o:%d' % obiekt.id)
    else:
        dane = dict(order_id=obiekt.order_id, product_id=obiekt.id, unit_key='p:%d' % obiekt.id)
    if odlozony is not None:
        dane.update(postponed_at=odlozony, postpone_reason='brak_materialu', postpone_note=u'czekamy na dąb')
    dane.update(kolumny)
    db.session.add(StationDesk(station_code=stanowisko, pulled_at=pobrano, zrodlo=zrodlo, **dane))
    db.session.commit()


def _pracownik(imie, nazwisko):
    from modules.production.models import ProductionWorker
    kto = ProductionWorker(first_name=imie, last_name=nazwisko, is_active=True)
    db.session.add(kto)
    db.session.commit()
    return kto


def test_stoly_panelu_ksztalt(client):
    kto = _pracownik('Adam', 'Kowalski')
    order = zam(statusy=('czeka_na_sklejanie',) * 4, gwiazdki=2, numer='5001')
    a, b, c, d = order.products
    kafel_stolu('gluing', a, zrodlo='biuro', sent_by_user_id=1)
    kafel_stolu('gluing', b, odlozony=datetime(2026, 10, 5, 9, 40), postponed_by_worker_id=kto.id)
    formatowane = zam(statusy=('czeka_na_formatowanie',), numer='5002')
    kafel_stolu('formatting', formatowane)

    r = client.get(BASE + '/stoly')

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert dane['success'] is True
    # sześć stanowisk ze stołem, w kolejności procesu (Lakiernia nie ma stołu)
    assert [st['stanowisko'] for st in dane['stanowiska']] == [
        'cutting', 'assembly', 'gluing', 'formatting', 'edges', 'packaging']
    sklejanie = dane['stanowiska'][2]
    assert set(sklejanie) == {'stanowisko', 'nazwa', 'tryb', 'jednostka', 'miejsca', 'limit_odlozen', 'stol',
                              'odlozone', 'kolejka_dalej', 'widma'}     # widma: krok K4b (raport K3, D2)
    assert (sklejanie['nazwa'], sklejanie['tryb'], sklejanie['jednostka'], sklejanie['miejsca'],
            sklejanie['limit_odlozen']) == ('Sklejanie', 'stary', 'pozycja', 2, 10)
    assert sklejanie['kolejka_dalej'] == 2
    (na_stole,) = sklejanie['stol']
    assert na_stole['unit_key'] == 'p:%d' % a.id and na_stole['product_id'] == a.id
    assert (na_stole['numer'], na_stole['short_id'], na_stole['gwiazdki']) == ('5001', a.short_product_id, 2)
    assert (na_stole['zrodlo'], na_stole['pobrano']) == ('biuro', T_STOL.isoformat())
    assert {'szczebel', 'termin', 'material', 'wymiary', 'dorobka', 'rozpoczete'} <= set(na_stole)
    (odlozony,) = sklejanie['odlozone']
    assert odlozony['unit_key'] == 'p:%d' % b.id
    assert (odlozony['powod'], odlozony['notatka'], odlozony['odlozono'], odlozony['pracownik']) == (
        'brak_materialu', u'czekamy na dąb', '2026-10-05T09:40:00', u'Adam Kowalski')
    formatowanie = dane['stanowiska'][3]
    assert formatowanie['jednostka'] == 'zamowienie'
    (kafel,) = formatowanie['stol']
    assert (kafel['unit_key'], kafel['order_id'], kafel['numer'], kafel['pozycji']) == (
        'o:%d' % formatowane.id, formatowane.id, '5002', 1)
    assert c.id and d.id


def test_stoly_panelu_bez_lakierni(client):
    zam(statusy=('czeka_na_lakiernie',))
    stanowiska = [st['stanowisko'] for st in client.get(BASE + '/stoly').get_json()['stanowiska']]
    assert 'painting' not in stanowiska and len(stanowiska) == 6


def test_stoly_panelu_kolejnosc_i_licznik_jak_na_tablecie(client):
    """Panel pokazuje to samo co tablet: kolejność `stol.kafle` i `kolejka_dalej` ze `stol.stan` (Pakowanie bez
    sposobu dostawy jest zwykłym kandydatem — spec 5.1 po logistyce 4.6)."""
    order = zam(statusy=('czeka_na_sklejanie',) * 4)
    p = order.products
    kafel_stolu('gluing', p[0], zrodlo='kolejka', pobrano=datetime(2026, 10, 5, 7, 0))
    kafel_stolu('gluing', p[1], zrodlo='start', pobrano=datetime(2026, 10, 5, 9, 0))
    kafel_stolu('gluing', p[2], zrodlo='dorobka', pobrano=datetime(2026, 10, 5, 10, 0))
    zam(statusy=('czeka_na_pakowanie',), override_delivery_method=None)
    from modules.production.logistics import sposoby
    zam(statusy=('czeka_na_pakowanie',), override_delivery_method=sposoby.KURIER)

    stanowiska = {st['stanowisko']: st for st in client.get(BASE + '/stoly').get_json()['stanowiska']}

    assert [k['unit_key'] for k in stanowiska['gluing']['stol']] == ['p:%d' % p[i].id for i in (2, 1, 0)]
    for kod in ('gluing', 'packaging'):
        db.session.rollback()
        assert stanowiska[kod]['kolejka_dalej'] == stol.stan(kod).kolejka_dalej, kod
    assert stanowiska['packaging']['kolejka_dalej'] == 2


def test_odlozenia_panelu_najdluzej_lezace_pierwsze(client):
    kto = _pracownik('Ewa', 'Nowak')
    order = zam(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'), numer='5010')
    pozniej, wczesniej = order.products
    kafel_stolu('gluing', pozniej, odlozony=datetime(2026, 10, 5, 9, 40), postponed_by_worker_id=kto.id)
    kafel_stolu('gluing', wczesniej, odlozony=datetime(2026, 10, 5, 8, 50))
    formatowane = zam(statusy=('czeka_na_formatowanie',), numer='5011')
    kafel_stolu('formatting', formatowane, odlozony=datetime(2026, 10, 5, 9, 0), postpone_reason='inne',
                postpone_note=u'czeka na szablon')
    na_stole = zam(statusy=('czeka_na_sklejanie',))
    kafel_stolu('gluing', na_stole.products[0])                    # leży na stole — nie jest odłożeniem

    r = client.get(BASE + '/odlozenia')

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert dane['success'] is True
    assert dane['odlozenia'] == [
        {'stanowisko': 'gluing', 'nazwa': 'Sklejanie', 'unit_key': 'p:%d' % wczesniej.id, 'order_id': order.id,
         'numer': '5010', 'product_id': wczesniej.id, 'short_id': wczesniej.short_product_id,
         'powod': 'brak_materialu', 'notatka': u'czekamy na dąb', 'odlozono': '2026-10-05T08:50:00',
         'pracownik': None},
        {'stanowisko': 'formatting', 'nazwa': 'Formatowanie', 'unit_key': 'o:%d' % formatowane.id,
         'order_id': formatowane.id, 'numer': '5011', 'product_id': None, 'short_id': None, 'powod': 'inne',
         'notatka': u'czeka na szablon', 'odlozono': '2026-10-05T09:00:00', 'pracownik': None},
        {'stanowisko': 'gluing', 'nazwa': 'Sklejanie', 'unit_key': 'p:%d' % pozniej.id, 'order_id': order.id,
         'numer': '5010', 'product_id': pozniej.id, 'short_id': pozniej.short_product_id,
         'powod': 'brak_materialu', 'notatka': u'czekamy na dąb', 'odlozono': '2026-10-05T09:40:00',
         'pracownik': u'Ewa Nowak'},
    ]


def test_stoly_i_odlozenia_bez_blokad_i_zapisow(client):
    """Oba odczyty panelu: żadnych blokad, zapisów ani commitów — i żadnego dopełniania stołu."""
    order = zam(statusy=('czeka_na_sklejanie',) * 3)
    kafel_stolu('gluing', order.products[0], odlozony=datetime(2026, 10, 5, 9, 0))

    from sqlalchemy import event
    with Zapytania() as z:
        sluchacz = _ze_znacznikiem_commitu(z)
        try:
            assert client.get(BASE + '/stoly').status_code == 200
            assert client.get(BASE + '/odlozenia').status_code == 200
        finally:
            event.remove(db.session, 'after_commit', sluchacz)

    sql = [wpis[0] for wpis in z.lista]
    assert len(sql) > 5
    assert not [s for s in sql if s.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]
    assert not [s for s in sql if s.startswith(('INSERT', 'UPDATE', 'DELETE'))]
    assert 'COMMIT' not in sql
    db.session.rollback()
    assert StationDesk.query.count() == 1
    assert stale.STOL_K == 2


# ══ Krok K3: „Wyślij na stanowisko” i „Zdejmij ze stołu” (spec 5.7) ═════════════════════════════════════════

@pytest.fixture()
def sygnaly_stanowisk(monkeypatch):
    """Kody stanowisk, którym router wysłał sygnał realtime (po commicie)."""
    from modules.production.services import realtime_service
    wyslane = []
    monkeypatch.setattr(realtime_service, 'publish_station_signal', lambda kod: wyslane.append(kod) or True)
    return wyslane


def test_wyslij_200_log_i_sygnal(client, sygnaly_stanowisk):
    order = zam(statusy=('czeka_na_sklejanie', 'czeka_na_formatowanie'), numer='5020')
    pozycja = order.products[0]

    r = client.post(BASE + '/stoly/gluing/wyslij', json={'order_id': order.id})

    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {'success': True, 'stanowisko': 'gluing', 'wynik': 'wyslano',
                            'wyslane': ['p:%d' % pozycja.id], 'przywrocone': [], 'juz_na_stole': []}
    db.session.rollback()
    wiersz = StationDesk.query.one()
    assert (wiersz.station_code, wiersz.unit_key, wiersz.zrodlo, wiersz.sent_by_user_id) == (
        'gluing', 'p:%d' % pozycja.id, 'biuro', 1)
    (log,) = PriorityLog.query.filter_by(action='wyslanie').all()
    assert (log.order_id, log.product_id, log.station_code, log.user_id) == (order.id, pozycja.id, 'gluing', 1)
    assert sygnaly_stanowisk == ['gluing']

    # drugi raz: kafel już leży — bez zmian, bez logu i bez sygnału
    r = client.post(BASE + '/stoly/gluing/wyslij', json={'order_id': order.id})
    assert r.status_code == 200
    assert (r.get_json()['wynik'], r.get_json()['juz_na_stole']) == ('juz_na_stole', ['p:%d' % pozycja.id])
    assert PriorityLog.query.filter_by(action='wyslanie').count() == 1
    assert sygnaly_stanowisk == ['gluing']

    # historia w modalu priorytetu zamówienia
    historia = client.get(BASE + '/zamowienia/%d/priorytet' % order.id).get_json()['historia']
    assert [(w['akcja'], w['stanowisko']) for w in historia] == [('wyslanie', 'gluing')]


def test_wyslij_dziala_w_trybie_stary_i_stol(client, sygnaly_stanowisk):
    pierwsze, drugie = zam(statusy=('czeka_na_sklejanie',)), zam(statusy=('czeka_na_sklejanie',))
    assert client.post(BASE + '/stoly/gluing/wyslij', json={'order_id': pierwsze.id}).status_code == 200
    ustaw(stale.klucz_tryb('gluing'), 'stol')
    assert client.post(BASE + '/stoly/gluing/wyslij', json={'order_id': drugie.id}).status_code == 200
    db.session.rollback()
    assert StationDesk.query.filter_by(zrodlo='biuro').count() == 2


def test_wyslij_kody_bledow(client, sygnaly_stanowisk):
    na_formatowaniu = zam(statusy=('czeka_na_formatowanie',))
    na_lakierni = zam(statusy=('czeka_na_lakiernie',))
    przypadki = [
        ('gluing', {'order_id': na_formatowaniu.id}, 409, 'brak_na_stanowisku'),
        ('painting', {'order_id': na_lakierni.id}, 409, 'stanowisko_bez_stolu'),
        ('gluing', {'order_id': 987654}, 404, 'zamowienie_nieznane'),
        ('nie-ma-takiego', {'order_id': na_formatowaniu.id}, 400, 'stanowisko_nieznane'),
        ('sawmill', {'order_id': na_formatowaniu.id}, 400, 'stanowisko_nieznane'),
        ('gluing', {}, 400, 'dane_niepoprawne'),
        ('gluing', {'order_id': '12'}, 400, 'dane_niepoprawne'),
        ('gluing', {'order_id': True}, 400, 'dane_niepoprawne'),
        ('gluing', None, 400, 'dane_niepoprawne'),
    ]
    for kod, cialo, status, blad in przypadki:
        r = client.post(BASE + '/stoly/%s/wyslij' % kod, json=cialo)
        assert r.status_code == status, (kod, cialo, r.get_json())
        dane = r.get_json()
        assert dane['success'] is False and dane['error'] == blad and dane['message'], (kod, cialo)
    db.session.rollback()
    assert StationDesk.query.count() == 0 and PriorityLog.query.count() == 0
    assert sygnaly_stanowisk == []


def test_wyslij_pakowanie_bez_sposobu_dostawy_200(client, sygnaly_stanowisk):
    """Po logistyce 4.6 „Wyślij” na Pakowanie nie odmawia zamówienia bez sposobu dostawy (spec 5.1; dawniej 409
    `delivery_method_not_set`)."""
    bez_sposobu = zam(statusy=('czeka_na_pakowanie',), override_delivery_method=None)

    r = client.post(BASE + '/stoly/packaging/wyslij', json={'order_id': bez_sposobu.id})

    assert r.status_code == 200, r.get_json()
    assert r.get_json()['wyslane'] == ['o:%d' % bez_sposobu.id]
    db.session.rollback()
    assert [(w.unit_key, w.zrodlo) for w in StationDesk.query.all()] == [('o:%d' % bez_sposobu.id, 'biuro')]


def test_wyslij_commit_przed_blokada_stanowiska(client, sygnaly_stanowisk):
    """Kolejność routera: commit (koniec migawki) → blokada stanowiska jako PIERWSZE polecenie nowej transakcji →
    odczyty bieżące → zapis → commit → sygnał."""
    from sqlalchemy import event
    order = zam(statusy=('czeka_na_sklejanie',))
    with Zapytania() as z:
        sluchacz = _ze_znacznikiem_commitu(z)
        try:
            r = client.post(BASE + '/stoly/gluing/wyslij', json={'order_id': order.id})
        finally:
            event.remove(db.session, 'after_commit', sluchacz)

    assert r.status_code == 200, r.get_json()
    blokada = next(i for i, (sql, parametry) in enumerate(z.lista)
                   if sql.startswith('SELECT') and 'FROM prod_config' in sql and sql.endswith(' FOR UPDATE')
                   and 'priorytety_blokada_gluing' in tuple(parametry or ()))
    assert z.lista[blokada - 1] == ('COMMIT', None)
    wstawka = next(i for i, (sql, _p) in enumerate(z.lista) if sql.startswith('INSERT INTO prod_station_desk'))
    assert ('COMMIT', None) in z.lista[wstawka:]
    assert sygnaly_stanowisk == ['gluing']


def test_wyslij_ponawia_raz_po_1213(client, monkeypatch, sygnaly_stanowisk):
    order = zam(statusy=('czeka_na_sklejanie',))
    oryginal = stol.wyslij
    proby = []

    def z_zakleszczeniem(*args, **kwargs):
        proby.append(1)
        if len(proby) == 1:
            oryginal(*args, **kwargs)
            raise _blad_mysql(1213)
        return oryginal(*args, **kwargs)

    monkeypatch.setattr(stol, 'wyslij', z_zakleszczeniem)
    r = client.post(BASE + '/stoly/gluing/wyslij', json={'order_id': order.id})

    assert r.status_code == 200 and len(proby) == 2
    db.session.rollback()
    assert StationDesk.query.count() == 1 and PriorityLog.query.filter_by(action='wyslanie').count() == 1


def test_zdejmij_200_i_404(client, sygnaly_stanowisk):
    order = zam(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    kafel_stolu('gluing', pozycja, odlozony=datetime(2026, 10, 5, 9, 0))
    klucz = 'p:%d' % pozycja.id

    r = client.post(BASE + '/stoly/gluing/zdejmij', json={'unit_key': klucz})

    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {'success': True, 'stanowisko': 'gluing', 'unit_key': klucz, 'order_id': order.id,
                            'product_id': pozycja.id, 'odlozony': True}
    db.session.rollback()
    assert StationDesk.query.count() == 0
    (log,) = PriorityLog.query.filter_by(action='zdjecie').all()
    assert (log.order_id, log.product_id, log.station_code, log.user_id) == (order.id, pozycja.id, 'gluing', 1)
    assert sygnaly_stanowisk == ['gluing']

    # kafla już nie ma
    r = client.post(BASE + '/stoly/gluing/zdejmij', json={'unit_key': klucz})
    assert r.status_code == 404 and r.get_json()['error'] == 'brak_kafla'
    for kod, cialo, status, blad in [('gluing', {'unit_key': 'kafel'}, 400, 'dane_niepoprawne'),
                                     ('gluing', {}, 400, 'dane_niepoprawne'),
                                     ('painting', {'unit_key': klucz}, 409, 'stanowisko_bez_stolu'),
                                     ('hala', {'unit_key': klucz}, 400, 'stanowisko_nieznane')]:
        r = client.post(BASE + '/stoly/%s/zdejmij' % kod, json=cialo)
        assert (r.status_code, r.get_json()['error']) == (status, blad), (kod, cialo)
    assert sygnaly_stanowisk == ['gluing']


# ══ Krok K3: start stołów (spec 5.8) ════════════════════════════════════════════════════════════════════════

def _zaczete(statusy, stanowisko, numer=None):
    """Zamówienie, w którym pierwsza pozycja ma na stanowisku licznik sztuk > 0 (ktoś już przy niej pracuje)."""
    order = zam(statusy=statusy, numer=numer)
    setattr(order.products[0], 'quantity_done_%s' % stanowisko, 1)
    db.session.commit()
    return order


def test_start_podglad_ksztalt_bez_zapisow(client):
    from sqlalchemy import event
    sklejane = _zaczete(('czeka_na_sklejanie', 'czeka_na_sklejanie'), 'gluing', numer='5030')
    formatowane = _zaczete(('czeka_na_formatowanie',), 'formatting', numer='5031')
    kafel_stolu('formatting', formatowane, zrodlo='start')
    zam(statusy=('czeka_na_lakiernie',))

    with Zapytania() as z:
        sluchacz = _ze_znacznikiem_commitu(z)
        try:
            r = client.get(BASE + '/start')
        finally:
            event.remove(db.session, 'after_commit', sluchacz)

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert dane['success'] is True
    assert [st['stanowisko'] for st in dane['stanowiska']] == [
        'cutting', 'assembly', 'gluing', 'formatting', 'edges', 'packaging']
    sklejanie, formatowanie = dane['stanowiska'][2], dane['stanowiska'][3]
    assert set(sklejanie) == {'stanowisko', 'nazwa', 'tryb', 'jednostka', 'miejsca', 'liczba', 'na_stole', 'kafle'}
    assert (sklejanie['nazwa'], sklejanie['tryb'], sklejanie['jednostka'], sklejanie['miejsca']) == (
        'Sklejanie', 'stary', 'pozycja', 2)
    assert (sklejanie['liczba'], sklejanie['na_stole']) == (1, 0)
    assert sklejanie['kafle'] == [{
        'unit_key': 'p:%d' % sklejane.products[0].id, 'order_id': sklejane.id, 'numer': '5030',
        'product_id': sklejane.products[0].id, 'short_id': sklejane.products[0].short_product_id,
        'powod': 'licznik', 'na_stole': False}]
    assert (formatowanie['liczba'], formatowanie['na_stole']) == (1, 1)
    assert formatowanie['kafle'][0]['unit_key'] == 'o:%d' % formatowane.id
    assert formatowanie['kafle'][0]['na_stole'] is True
    # podgląd niczego nie zapisuje i niczego nie blokuje
    sql = [wpis[0] for wpis in z.lista]
    assert not [s for s in sql if s.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]
    assert not [s for s in sql if s.startswith(('INSERT', 'UPDATE', 'DELETE'))] and 'COMMIT' not in sql
    db.session.rollback()
    assert StationDesk.query.count() == 1


def test_start_przygotuj_admin_i_osobne_transakcje(client, sygnaly_stanowisk):
    """„Przygotuj stoły” (admin): stanowisko po stanowisku, każde we własnej transakcji — commit, blokada stanowiska
    jako pierwsze polecenie, zapis, commit — z logiem `start_stolow` i sygnałem po commicie."""
    from sqlalchemy import event
    sklejane = _zaczete(('czeka_na_sklejanie',), 'gluing')
    pakowane = _zaczete(('czeka_na_pakowanie',), 'packaging')
    pakowane.override_delivery_method = 'kurier'
    from modules.production.logistics import sposoby
    pakowane.override_delivery_method = sposoby.KURIER
    db.session.commit()

    with Zapytania() as z:
        sluchacz = _ze_znacznikiem_commitu(z)
        try:
            r = client.post(BASE + '/start/przygotuj')
        finally:
            event.remove(db.session, 'after_commit', sluchacz)

    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {'success': True, 'stanowiska': [
        {'stanowisko': 'cutting', 'dodane': 0, 'juz_byly': 0},
        {'stanowisko': 'assembly', 'dodane': 0, 'juz_byly': 0},
        {'stanowisko': 'gluing', 'dodane': 1, 'juz_byly': 0},
        {'stanowisko': 'formatting', 'dodane': 0, 'juz_byly': 0},
        {'stanowisko': 'edges', 'dodane': 0, 'juz_byly': 0},
        {'stanowisko': 'packaging', 'dodane': 1, 'juz_byly': 0},
    ]}
    db.session.rollback()
    assert sorted((w.station_code, w.unit_key, w.zrodlo, w.sent_by_user_id) for w in StationDesk.query.all()) == [
        ('gluing', 'p:%d' % sklejane.products[0].id, 'start', 1),
        ('packaging', 'o:%d' % pakowane.id, 'start', 1)]
    logi = PriorityLog.query.filter_by(action='start_stolow').order_by(PriorityLog.id).all()
    assert [(w.station_code, w.new_value, w.user_id) for w in logi] == [
        ('cutting', '0', 1), ('assembly', '0', 1), ('gluing', '1', 1), ('formatting', '0', 1), ('edges', '0', 1),
        ('packaging', '1', 1)]
    assert sygnaly_stanowisk == ['gluing', 'packaging']
    # sześć blokad stanowisk, każda zaraz po commicie (osobne transakcje), w kolejności procesu
    blokady = [(i, [p for p in parametry if str(p).startswith('priorytety_blokada_')][0])
               for i, (sql, parametry) in enumerate(z.lista)
               if sql.startswith('SELECT') and 'FROM prod_config' in sql and sql.endswith(' FOR UPDATE')]
    assert [klucz for _i, klucz in blokady] == ['priorytety_blokada_' + kod for kod in (
        'cutting', 'assembly', 'gluing', 'formatting', 'edges', 'packaging')]
    assert all(z.lista[i - 1] == ('COMMIT', None) for i, _klucz in blokady)

    # drugi przebieg: nic nowego
    r = client.post(BASE + '/start/przygotuj')
    assert [st['dodane'] for st in r.get_json()['stanowiska']] == [0] * 6
    assert [st['juz_byly'] for st in r.get_json()['stanowiska']] == [0, 0, 1, 0, 0, 1]
    assert sygnaly_stanowisk == ['gluing', 'packaging']


def test_start_przygotuj_403_bez_admina(client, monkeypatch, sygnaly_stanowisk):
    _zaczete(('czeka_na_sklejanie',), 'gluing')
    monkeypatch.setattr(_UzytkownikTestowy, 'role', 'user')

    r = client.post(BASE + '/start/przygotuj')

    assert r.status_code == 403
    assert r.get_json() == {'success': False, 'error': 'Brak uprawnień administratora'}
    db.session.rollback()
    assert StationDesk.query.count() == 0
    # podgląd startu jest dla biura (guard), nie tylko dla admina
    assert client.get(BASE + '/start').status_code == 200


def test_start_przygotuj_blad_stanowiska_nie_cofa_poprzednich(client, monkeypatch, sygnaly_stanowisk):
    sklejane = _zaczete(('czeka_na_sklejanie',), 'gluing')
    _zaczete(('czeka_na_formatowanie',), 'formatting')
    oryginal = stol.przygotuj_start

    def awaria_formatowania(kod, user_id, **kwargs):
        if kod == 'formatting':
            raise RuntimeError('sztuczna awaria')
        return oryginal(kod, user_id, **kwargs)

    monkeypatch.setattr(stol, 'przygotuj_start', awaria_formatowania)
    r = client.post(BASE + '/start/przygotuj')

    assert r.status_code == 500
    dane = r.get_json()
    assert (dane['success'], dane['error'], dane['nieudane']) == (False, 'blad_serwera', 'formatting')
    assert [st['stanowisko'] for st in dane['stanowiska']] == ['cutting', 'assembly', 'gluing']
    assert 'sztuczna awaria' not in r.get_data(as_text=True)
    db.session.rollback()
    assert [w.unit_key for w in StationDesk.query.all()] == ['p:%d' % sklejane.products[0].id]


# ══ Krok K4b: terminy w PUT /ustawienia (plan K4b, Doprecyzowania 5) ═════════════════════════════════════════

def test_ustawienia_terminow_odczyt_domyslny(client):
    """Bez wierszy `prod_config` — wartości domyślne `config_service` (te same, których używa import z Base.)."""
    dane = client.get(BASE + '/ustawienia').get_json()
    assert (dane['deadline_default_days'], dane['deadline_finished_days']) == (10, 14)
    from modules.production.services.config_service import get_config_service
    domyslne = get_config_service()._default_values
    assert (domyslne['DEADLINE_DEFAULT_DAYS'], domyslne['DEADLINE_FINISHED_DAYS']) == (10, 14)


def test_ustawienia_terminow_przez_put(client, utrwal_atrapa):
    r = client.put(BASE + '/ustawienia', json={'deadline_finished_days': 10})
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['zmienione'] == ['DEADLINE_FINISHED_DAYS']
    assert dane['przeliczenie'] == 'niepotrzebne' and utrwal_atrapa == []
    from modules.production.models import ProductionConfig
    wiersz = ProductionConfig.query.filter_by(config_key='DEADLINE_FINISHED_DAYS').one()
    assert (wiersz.config_value, wiersz.config_type) == ('10', 'integer')
    (wpis,) = PriorityLog.query.filter_by(action='ustawienia', note='DEADLINE_FINISHED_DAYS').all()
    assert wpis.new_value == '10' and wpis.order_id is None
    assert client.get(BASE + '/ustawienia').get_json()['deadline_finished_days'] == 10
    assert client.put(BASE + '/ustawienia', json={'deadline_default_days': 12}).get_json()['deadline_default_days'] == 12


@pytest.mark.parametrize('pole', ['deadline_default_days', 'deadline_finished_days'])
@pytest.mark.parametrize('wartosc', [0, 91, True, '10'])
def test_ustawienia_terminow_walidacja_400(client, utrwal_atrapa, pole, wartosc):
    r = client.put(BASE + '/ustawienia', json={pole: wartosc})
    assert r.status_code == 400
    dane = r.get_json()
    assert dane['error'] == 'ustawienie_niepoprawne' and dane['pole'] == pole
    from modules.production.models import ProductionConfig
    assert ProductionConfig.query.filter(ProductionConfig.config_key.like('DEADLINE_%')).count() == 0
