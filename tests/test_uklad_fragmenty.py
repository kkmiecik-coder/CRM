# -*- coding: utf-8 -*-
"""Endpointy oddające gotowy kawałek widoku: jeden kafelek i cała siatka.

Istnieją po to, żeby pulpit dało się przerysować BEZ przeładowania strony,
a mimo to znaczniki kafelków nadal generował serwer. Gdyby budował je
JavaScript, powstałoby drugie źródło prawdy o wyglądzie całego pulpitu.

CZEGO TE TESTY NIE GWARANTUJĄ: że wstawiony fragment wygląda w przeglądarce
tak samo, jak ten sam kafelek wyrenderowany razem ze stroną. Porównują ŹRÓDŁO.
Że wygląda, dowodzi krok „obejrzyj w przeglądarce" z Zadania 12.

Fikstury jak w tests/test_uklad_api.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from bs4 import BeautifulSoup
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import reports_bp
from modules.reports.uklad import KATALOG, UKLAD_DOMYSLNY, Instancja, wymiary_typu  # noqa: F401

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)


@compiles(LONGTEXT, 'sqlite')
def _longtext_jako_text(typ, kompilator, **kw):
    return 'TEXT'


from modules.production.models import ProductionOrder  # noqa: F401,E402
from modules.users.models import User  # noqa: E402
from modules.clients.models import Client  # noqa: F401,E402
import modules.quotes.models  # noqa: F401,E402
from modules.quotes.models import QuoteStatus  # noqa: F401,E402

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATYKA_PRODUKCJI = os.path.join(KORZEN, 'modules', 'production', 'static')


# --- fikstury: te same co w tests/test_uklad_api.py -------------------------
# Kopia, a nie import: pytest nie widzi fikstur spoza conftestu.

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


def kafelek(client, **parametry):
    adres = '/reports/api/kafelek?' + '&'.join(
        f'{k}={v}' for k, v in parametry.items())
    return client.get(adres)


# --- /api/kafelek: poprawne wejście -----------------------------------------

def test_oddaje_html_klucz_i_dane(client):
    odp = kafelek(client, typ='kanal', wymiar='caretaker')
    assert odp.status_code == 200
    tresc = odp.get_json()
    assert set(tresc) == {'klucz', 'html', 'dane'}
    assert tresc['klucz'] == 'kanal:caretaker'


def test_html_to_jedna_sekcja_kafelka(client):
    tresc = kafelek(client, typ='kanal', wymiar='caretaker').get_json()
    zupa = BeautifulSoup(tresc['html'], 'html.parser')
    sekcje = zupa.find_all('section', recursive=False)
    assert len(sekcje) == 1
    assert sekcje[0].get('data-klucz') == 'kanal:caretaker'
    assert sekcje[0].get('data-typ') == 'kanal'
    assert sekcje[0].get('data-wymiar') == 'caretaker'


def test_fragment_jest_identyczny_z_tym_co_renderuje_strona(client):
    """NAJWAŻNIEJSZY test tego pliku. Gdyby fragment różnił się od kafelka
    wyrenderowanego razem ze stroną, użytkownik dostawałby po zmianie wymiaru
    kartę, która wygląda inaczej niż przed zmianą — i nikt by nie wiedział,
    która wersja jest właściwa."""
    zapisz(client, [{'typ': 'kanal', 'wymiar': 'caretaker'}])
    ze_strony = BeautifulSoup(client.get('/reports/analiza').get_data(as_text=True),
                              'html.parser').select_one('[data-kafelek]')
    z_fragmentu = BeautifulSoup(
        kafelek(client, typ='kanal', wymiar='caretaker').get_json()['html'],
        'html.parser').select_one('[data-kafelek]')
    assert str(z_fragmentu) == str(ze_strony)


# KAŻDY typ katalogu w swoim wymiarze domyślnym — nie tylko te z układu
# domyślnego. Od partii E (punkt E1) należności nie stoją na pulpicie
# domyślnym, a dalej da się je dodać, więc ich fragment też ma się zgadzać.
INSTANCJE_KATALOGU = [Instancja(typ, KATALOG[typ].domyslny_wymiar
                                if KATALOG[typ].wymiarowy else None)
                      for typ in KATALOG]


@pytest.mark.parametrize('instancja', INSTANCJE_KATALOGU, ids=lambda i: i.klucz)
def test_fragment_kazdego_typu_jest_identyczny_z_kafelkiem_strony(client, instancja):
    """Dopisane ponad plan: ten sam dowód dla KAŻDEGO z jedenastu typów, nie
    tylko dla kanałów. Karty kubełkowe mają własną listę wymiarów, mapa
    prefiks identyfikatorów, KPI kanwę — każda z tych rzeczy mogłaby się
    rozjechać między stroną a fragmentem niezależnie od pozostałych."""
    if instancja not in UKLAD_DOMYSLNY:
        # Typ spoza układu domyślnego stawiamy na pulpicie tak, jak zrobi to
        # użytkownik — zapisem układu — żeby strona miała go czym wyrenderować.
        assert zapisz(client, [{'typ': i.typ, 'wymiar': i.wymiar}
                               for i in list(UKLAD_DOMYSLNY) + [instancja]]).status_code == 200
    ze_strony = BeautifulSoup(client.get('/reports/analiza').get_data(as_text=True),
                              'html.parser').select_one(f'[data-klucz="{instancja.klucz}"]')
    parametry = {'typ': instancja.typ}
    if instancja.wymiar:
        parametry['wymiar'] = instancja.wymiar
    z_fragmentu = BeautifulSoup(kafelek(client, **parametry).get_json()['html'],
                                'html.parser').select_one('[data-kafelek]')
    assert str(z_fragmentu) == str(ze_strony)


def test_html_nie_niesie_zadnej_liczby(client):
    """Fragment to CZYSTY SZKIELET. Wszystkie wartości — w tym wolny tekst
    z BaseLinkera — wchodzą dopiero w kroku rysowania, przez textContent.
    Dzięki temu wstawienie fragmentu jest bezpieczne."""
    tresc = kafelek(client, typ='kanal', wymiar='caretaker').get_json()
    zupa = BeautifulSoup(tresc['html'], 'html.parser')
    for wiersz in zupa.select('.an-wiersz'):
        assert wiersz.get_text(strip=True) == '', 'w szkielecie jest wartość'


def test_cena_z_wykonczeniem_stoi_tylko_na_wymiarze_wykonczenia(client):
    """Porządki końcowe, punkt 2: podsekcja „Cena za m³ z wykończeniem" jest
    porównaniem wykończeń z surowym. Karta pierścienia przełączona na inny
    wymiar (np. Status) nie ma czego w niej pokazać — szablon jej nie rysuje,
    a serwer jej nie liczy (test w test_analiza_uklad_dane.py)."""
    html = kafelek(client, typ='wykonczenie', wymiar='finish_state').get_json()['html']
    zupa = BeautifulSoup(html, 'html.parser')
    assert zupa.find(attrs={'data-pole': 'wykonczenie:finish_state.roznica'}) is not None
    assert 'Cena za m³ z wykończeniem' in zupa.get_text()

    for wymiar in ('current_status', 'wood_species'):
        html = kafelek(client, typ='wykonczenie', wymiar=wymiar).get_json()['html']
        zupa = BeautifulSoup(html, 'html.parser')
        assert zupa.find(attrs={'data-pole': f'wykonczenie:{wymiar}.roznica'}) is None, wymiar
        assert 'z wykończeniem' not in zupa.get_text(), wymiar


def test_dane_sa_payloadem_dla_jednej_instancji(client):
    tresc = kafelek(client, typ='kanal', wymiar='caretaker').get_json()
    assert set(tresc['dane']['karty']) == {'kanal:caretaker'}


def test_dane_nie_licza_paska_wskaznikow_dla_zwyklego_kafelka(client):
    """Jeden kafelek to jeden kafelek — pasek KPI i wykres trendu kosztują
    26 ms i nikt ich tu nie ogląda (Zadanie 5, `TYPY_CZYTAJACE_KPI`)."""
    tresc = kafelek(client, typ='kanal', wymiar='caretaker').get_json()
    assert tresc['dane']['kpi'] is None
    assert tresc['dane']['trend'] is None


def test_kafelek_kpi_dostaje_swoj_pasek_i_trend(client):
    tresc = kafelek(client, typ='kpi').get_json()
    assert tresc['dane']['kpi'] is not None
    assert tresc['dane']['trend'] is not None


def test_kafelek_kubelkowy_dziala_z_pseudo_wymiarem(client):
    from modules.reports.analiza_service import KARTY_KUBELKOWE
    wymiar = KARTY_KUBELKOWE['klienci']['domyslny']
    tresc = kafelek(client, typ='klienci', wymiar=wymiar).get_json()
    assert tresc['klucz'] == f'klienci:{wymiar}'
    assert 'kubelki' in tresc['dane']['karty'][tresc['klucz']]


def test_segment_porownawczy_przechodzi_do_fragmentu(client):
    tresc = kafelek(client, typ='kanal', wymiar='caretaker',
                    porownanie='order_source:shop').get_json()
    assert tresc['dane']['porownanie'] is not None


# --- /api/kafelek: wejście złe ----------------------------------------------

def test_nieznany_typ_daje_400(client):
    odp = kafelek(client, typ='wykres-slonca')
    assert odp.status_code == 400
    assert odp.get_json()['error'] == 'zly_kafelek'


def test_brak_typu_daje_400(client):
    assert client.get('/reports/api/kafelek').status_code == 400


def test_wymiar_spoza_listy_typu_daje_400(client):
    """Ta sama reguła, co przy zapisie: karta należności przyjmuje wyłącznie
    kolumny poziomu ZAMÓWIENIA, bo saldo żyje na zamówieniu."""
    spoza = next(w for w in wymiary_typu('kanal')
                 if w not in wymiary_typu('naleznosci'))
    odp = kafelek(client, typ='naleznosci', wymiar=spoza)
    assert odp.status_code == 400


def test_typ_wymiarowy_bez_wymiaru_daje_400(client):
    assert kafelek(client, typ='kanal').status_code == 400


def test_typ_bez_wymiaru_z_wymiarem_daje_400(client):
    assert kafelek(client, typ='kpi', wymiar='caretaker').status_code == 400


def test_zly_okres_daje_400_a_nie_500(client):
    odp = kafelek(client, typ='kpi', od='wczoraj', do='2026-09-23')
    assert odp.status_code == 400
    assert odp.get_json()['error'] == 'zly_okres'


def test_zly_filtr_daje_400_a_nie_500(client):
    odp = kafelek(client, typ='kanal', wymiar='caretaker', porownanie='bez-dwukropka')
    assert odp.status_code == 400


def test_komunikat_bledu_nie_wkleja_dlugiego_wejscia(client):
    """Dopisane ponad plan. Komunikat idzie wprost na ekran; wartość z adresu
    ma być w nim co najwyżej ucięta — ta sama zasada, co w `uklad._cytuj`."""
    odp = kafelek(client, typ='x' * 500)
    assert odp.status_code == 400
    assert len(odp.get_json()['komunikat']) < 150


def test_bez_sesji_daje_401(app):
    assert app.test_client().get('/reports/api/kafelek?typ=kpi').status_code == 401


def test_jeden_kafelek_to_jeden_kafelek(client):
    """Endpoint nie przyjmuje LISTY kafelków i nie ma jak poprosić nim
    o dwieście agregatów w jednym żądaniu — limit 20 zostaje nietknięty."""
    tresc = kafelek(client, typ='kanal', wymiar='caretaker').get_json()
    assert len(tresc['dane']['karty']) == 1


# --- /api/siatka -------------------------------------------------------------

def test_siatka_oddaje_wszystkie_kafelki_zapisanego_ukladu(client):
    tresc = client.get('/reports/api/siatka').get_json()
    zupa = BeautifulSoup(tresc['html'], 'html.parser')
    assert len(zupa.select('[data-kafelek]')) == len(UKLAD_DOMYSLNY)


def test_siatka_idzie_za_zapisanym_ukladem(client):
    zapisz(client, [{'typ': 'kpi', 'wymiar': None}])
    zupa = BeautifulSoup(client.get('/reports/api/siatka').get_json()['html'],
                         'html.parser')
    assert [w.get('data-klucz') for w in zupa.select('[data-kafelek]')] == ['kpi']


def test_siatka_przy_pustym_ukladzie_oddaje_pusty_html(client):
    zapisz(client, [])
    tresc = client.get('/reports/api/siatka').get_json()
    assert BeautifulSoup(tresc['html'], 'html.parser').select('[data-kafelek]') == []


def test_siatka_niesie_liczbe_pominietych(client, uzytkownik):
    from extensions import db
    from modules.reports.models_uklad import UkladDashboardu
    db.session.add(UkladDashboardu(
        user_id=uzytkownik.id,
        uklad=[{'typ': 'kpi', 'wymiar': None},
               {'typ': 'karta-ktorej-nie-ma', 'wymiar': None}]))
    db.session.commit()
    assert client.get('/reports/api/siatka').get_json()['pominietych'] == 1


def test_siatka_nie_zawiera_kafelka_dodawania(client):
    """Kafelek „+" należy do trybu edycji i dokłada go strona, nie fragment —
    inaczej po anulowaniu edycji w siatce byłyby dwa."""
    assert 'an-kafelek--dodaj' not in client.get('/reports/api/siatka').get_json()['html']


def test_siatka_jest_ta_sama_co_na_stronie(client):
    """Dopisane ponad plan. Fragment siatki i siatka strony pochodzą z tego
    samego pliku `_siatka.html` — kafelki mają być identyczne co do znaku.

    Jedyna różnica to kafelek „+ Dodaj statystykę" (Zadanie 11): strona
    włącza `_siatka.html` z flagą `z_kafelkiem_dodawania`, fragment — bez niej
    (patrz test_siatka_nie_zawiera_kafelka_dodawania). Na stronie „+" jest
    więc OSTATNIM dzieckiem siatki i poza nim dzieci obu siatek są te same."""
    zapisz(client, [{'typ': 'kanal', 'wymiar': 'caretaker'},
                    {'typ': 'wojewodztwo', 'wymiar': 'delivery_state'}])
    ze_strony = BeautifulSoup(client.get('/reports/analiza').get_data(as_text=True),
                              'html.parser').select_one('#an-siatka')
    z_fragmentu = BeautifulSoup(client.get('/reports/api/siatka').get_json()['html'],
                                'html.parser').select_one('#an-siatka')
    dzieci_strony = ze_strony.find_all(True, recursive=False)
    assert dzieci_strony[-1].get('id') == 'an-dodaj-kafelek'
    assert [str(d) for d in dzieci_strony[:-1]] == \
        [str(d) for d in z_fragmentu.find_all(True, recursive=False)]
    assert ze_strony.attrs == z_fragmentu.attrs


def test_siatka_zly_okres_daje_400_a_nie_500(client):
    """Dopisane ponad plan: kod planu wołał `parsuj_okres` bez straży."""
    odp = client.get('/reports/api/siatka?od=wczoraj')
    assert odp.status_code == 400
    assert odp.get_json()['error'] == 'zly_okres'


def test_siatka_bez_sesji_daje_401(app):
    assert app.test_client().get('/reports/api/siatka').status_code == 401
