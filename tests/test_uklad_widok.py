# -*- coding: utf-8 -*-
"""Pulpit renderowany Z UKŁADU: jedna siatka, kafelki z tożsamością instancji.

Fikstury jak w tests/test_uklad_api.py.

CZEGO TE TESTY NIE GWARANTUJĄ: że siatka wygląda tak, jak wyglądała. Sprawdzają
STRUKTURĘ źródła. Że układ domyślny daje ten sam obraz co przed zmianą, dowodzi
wyłącznie krok „obejrzyj w przeglądarce" z tego zadania.
"""
import os
import re
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
from modules.reports.uklad import KATALOG, UKLAD_DOMYSLNY

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
SCIEZKA_CSS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'css', 'analiza.css')
SCIEZKA_JS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'analiza.js')


# --- fikstury: te same trzy co w tests/test_uklad_api.py --------------------
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


def zupa(client, adres='/reports/analiza'):
    odpowiedz = client.get(adres)
    assert odpowiedz.status_code == 200
    return BeautifulSoup(odpowiedz.get_data(as_text=True), 'html.parser')


def css():
    with open(SCIEZKA_CSS, encoding='utf-8') as plik:
        return plik.read()


def js_bez_komentarzy():
    """Źródło JS z WYCIĘTYMI komentarzami.

    Powód: w tym repo zdarzył się już test JS, który przechodził, bo szukanego
    napisu było w KOMENTARZU. Test, który da się spełnić komentarzem, nie jest
    testem."""
    with open(SCIEZKA_JS, encoding='utf-8') as plik:
        zrodlo = plik.read()
    zrodlo = re.sub(r'/\*.*?\*/', '', zrodlo, flags=re.S)
    zrodlo = re.sub(r'(?m)^\s*//.*$', '', zrodlo)
    return zrodlo


# --- jedna siatka zamiast trzech rzędów -------------------------------------

def test_strona_ma_dokladnie_jedna_siatke(client):
    assert len(zupa(client).select('.an-siatka')) == 1


def test_strona_nie_ma_juz_trzech_rzedow(client):
    """Trzy osobne siatki uniemożliwiają dowolne przestawianie kafelków —
    kafelek nie ma jak przejść z rzędu do rzędu."""
    strona = zupa(client)
    for klasa in ('an-rzad--1', 'an-rzad--2', 'an-rzad--3'):
        assert not strona.select('.' + klasa), klasa


def test_css_zna_siatke_i_szeroki_kafelek():
    tresc = css()
    assert '.an-siatka' in tresc
    assert '.an-kafelek--szeroki' in tresc


def test_css_nie_definiuje_juz_starych_rzedow():
    tresc = css()
    for klasa in ('.an-rzad--1', '.an-rzad--2', '.an-rzad--3'):
        assert klasa not in tresc, klasa


def test_siatka_ma_cztery_kolumny_jak_dzis():
    """Dzisiejszy rząd 1 to `2fr 1fr 1fr`, a rzędy 2 i 3 to `repeat(4, 1fr)`.
    To jest ta sama siatka czterech jednostek: KPI zajmuje dwie, reszta po
    jednej. Jedna siatka odtwarza dzisiejszy układ co do rozmieszczenia."""
    assert 'repeat(4, minmax(0, 1fr))' in css()


# --- kafelek ma tożsamość instancji -----------------------------------------

def test_uklad_domyslny_daje_jedenascie_kafelkow(client):
    assert len(zupa(client).select('[data-kafelek]')) == len(UKLAD_DOMYSLNY)


def test_kazdy_kafelek_niesie_klucz_typ_i_wymiar(client):
    for kafelek in zupa(client).select('[data-kafelek]'):
        assert kafelek.get('data-klucz')
        typ = kafelek.get('data-typ')
        assert typ in KATALOG
        if KATALOG[typ].wymiarowy:
            assert kafelek.get('data-wymiar')


def test_kolejnosc_kafelkow_w_domu_to_kolejnosc_ukladu(client):
    klucze = [k.get('data-klucz') for k in zupa(client).select('[data-kafelek]')]
    assert klucze == [i.klucz for i in UKLAD_DOMYSLNY]


def test_tylko_kpi_jest_szeroki(client):
    szerokie = [k.get('data-typ') for k in zupa(client).select('.an-kafelek--szeroki')]
    assert szerokie == ['kpi']


def test_cialo_kafelka_jest_kluczowane_instancja(client):
    """`data-cialo="kanal"` nie identyfikuje kafelka, gdy kafelków kanałów
    jest trzy."""
    strona = zupa(client)
    for kafelek in strona.select('[data-kafelek]'):
        cialo = kafelek.select_one('[data-cialo]')
        if cialo is not None:
            assert cialo.get('data-cialo') == kafelek.get('data-klucz')


def test_dwa_kafelki_tego_samego_typu_maja_rozne_klucze(client):
    zapisz(client, [{'typ': 'kanal', 'wymiar': 'order_source'},
                    {'typ': 'kanal', 'wymiar': 'caretaker'}])
    klucze = [k.get('data-klucz') for k in zupa(client).select('[data-kafelek]')]
    assert klucze == ['kanal:order_source', 'kanal:caretaker']


def test_identyfikatory_elementow_nie_powtarzaja_sie_przy_dwoch_takich_samych_kafelkach(client):
    """Canvas wykresu miał do 23.09.2026 stały `id`. Dwa kafelki wykończenia
    dałyby dwa elementy o tym samym `id` i Chart.js rysowałby oba w pierwszym."""
    zapisz(client, [{'typ': 'wykonczenie', 'wymiar': 'finish_state'},
                    {'typ': 'wykonczenie', 'wymiar': 'wood_species'}])
    strona = zupa(client)
    identyfikatory = [w.get('id') for w in strona.select('[id]')]
    assert len(identyfikatory) == len(set(identyfikatory)), \
        [i for i in identyfikatory if identyfikatory.count(i) > 1]


def test_dwie_mapy_w_ukladzie_nie_dubluja_identyfikatorow(client):
    """Dopisane ponad plan. Każdy kafelek województw niesie w szkielecie mapę
    z szesnastoma ścieżkami, a ścieżki mają `id` województw — bez prefiksu
    kafelka dwa kafelki mapy dawałyby szesnaście zdublowanych identyfikatorów."""
    zapisz(client, [{'typ': 'wojewodztwo', 'wymiar': 'delivery_state'},
                    {'typ': 'wojewodztwo', 'wymiar': 'caretaker'}])
    strona = zupa(client)
    identyfikatory = [w.get('id') for w in strona.select('[id]')]
    assert len(identyfikatory) == len(set(identyfikatory)), \
        [i for i in identyfikatory if identyfikatory.count(i) > 1]
    # Obszar jest nadal rozpoznawalny bez prefiksu — po nim szuka analiza.js.
    for kafelek in strona.select('[data-kafelek]'):
        assert kafelek.select_one('path[data-obszar="mazowieckie"]') is not None


# --- selektory nadal spełniają niezmiennik z 23.09.2026 ---------------------

def test_kazdy_select_an_sel_ma_rodzica_an_sel_opak(client):
    """Ten sam niezmiennik, który uratował zakładkę 23.09.2026: `.an-sel` ma
    position:absolute z inset:0, więc bez pozycjonowanego rodzica przykrywa
    całe okno i połyka WSZYSTKIE kliknięcia. Przy generowanych kafelkach
    łatwo o to potknięcie, bo selektor powstaje w makrze."""
    for wybor in zupa(client).select('select.an-sel'):
        assert 'an-sel-opak' in (wybor.parent.get('class') or []), wybor


def test_kazdy_kafelek_wymiarowy_ma_selektor_ze_swoim_wymiarem(client):
    for kafelek in zupa(client).select('[data-kafelek]'):
        if not KATALOG[kafelek.get('data-typ')].wymiarowy:
            continue
        wybor = kafelek.select_one('select.an-sel')
        assert wybor is not None, kafelek.get('data-klucz')
        wybrana = wybor.select_one('option[selected]')
        assert wybrana.get('value') == kafelek.get('data-wymiar')


def test_selektor_niesie_klucz_instancji_a_nie_sam_typ(client):
    for wybor in zupa(client).select('select[data-selektor]'):
        assert ':' in wybor.get('data-selektor') or \
            not KATALOG[wybor.get('data-selektor')].wymiarowy


# --- wyjścia w stopkach -----------------------------------------------------

def test_wyjscie_kafelka_niesie_jego_wlasny_wymiar(client):
    zapisz(client, [{'typ': 'kanal', 'wymiar': 'caretaker'}])
    kafelek = zupa(client).select_one('[data-kafelek]')
    wyjscie = kafelek.select_one('a[data-wyjscie-miara]')
    assert wyjscie.get('data-wyjscie-wymiar') == 'caretaker'


def test_wyjscie_karty_klientow_idzie_za_jej_wymiarem(client):
    """Weryfikacja partii E: stopka „Klienci według" prowadziła zawsze do
    Eksploratora po pochodzeniu klienta, choć karta stała na opiekunie.
    Karta na wymiarze z rejestru prowadzi po TYM wymiarze, jak inne karty;
    kubełki (pseudo-wymiar spoza rejestru, Eksplorator go nie zna) — po
    pierwszym wymiarze karty z katalogu kart kubełkowych."""
    from modules.reports.analiza_service import KARTY_KUBELKOWE
    zapisz(client, [{'typ': 'klienci', 'wymiar': 'caretaker'},
                    {'typ': 'klienci', 'wymiar': 'liczba_zamowien'}])
    strona = zupa(client)
    oczekiwane = {'klienci:caretaker': 'caretaker',
                  'klienci:liczba_zamowien': KARTY_KUBELKOWE['klienci']['wymiary'][0]}
    for klucz, wymiar in oczekiwane.items():
        wyjscie = strona.select_one(f'[data-klucz="{klucz}"] a[data-wyjscie-miara]')
        assert wyjscie.get('data-wyjscie-wymiar') == wymiar, klucz
        assert f'wymiar={wymiar}' in wyjscie.get('href'), klucz
    # Szablon nie wpisuje wymiaru wyjścia karty klientów na sztywno.
    sciezka = os.path.join(KORZEN, 'modules', 'reports', 'templates',
                           'analiza', '_kafelki.html')
    with open(sciezka, encoding='utf-8') as plik:
        assert "wymiar='client_origin'" not in plik.read()


def test_js_nie_sklada_juz_wyjscia_z_mapy_wymiarow_karty(client):
    """`stan.wymiary` znika razem z parametrami `?kanal=` w adresie."""
    assert 'stan.wymiary' not in js_bez_komentarzy()


# --- pętla renderowania -----------------------------------------------------

def test_js_iteruje_po_kafelkach_zamiast_wypisywac_klucze():
    zrodlo = js_bez_komentarzy()
    assert 'data-kafelek' in zrodlo
    assert "dane.karty[" in zrodlo


def test_js_nie_ma_juz_zaszytych_kluczy_kart():
    """Zaszyty klucz działa dla jednego kafelka danego typu i milczy przy drugim."""
    zrodlo = js_bez_komentarzy()
    for zaszyte in ("'kanal'", "'opiekun'", "'wojewodztwo'", "'dostawa'"):
        assert f'rysujWiersze({zaszyte}' not in zrodlo


def test_js_pomija_kafelek_bez_danych_zamiast_sie_wywalac():
    """Kafelek dodany w trybie edycji nie ma jeszcze danych — ma zostać
    szkieletem, a nie wywrócić całego renderu."""
    assert 'if (!karta)' in js_bez_komentarzy()


def test_js_zapisuje_uklad_pod_adresem_z_atrybutu_danych():
    zrodlo = js_bez_komentarzy()
    assert 'dataset.urlUklad' in zrodlo or "getAttribute('data-url-uklad')" in zrodlo
    assert "'/reports/api/uklad'" not in zrodlo, 'adres sklejony na sztywno'


def test_js_ma_nazwana_funkcje_rysujaca_jeden_kafelek():
    """Zadania 9, 11 i 12 wstawiaja kafelek w miejscu i wolaja DOKLADNIE te
    funkcje. Bez niej powstalyby cztery sciezki rysowania tego samego."""
    assert 'function rysujKafelek(' in js_bez_komentarzy()


def test_js_rysuje_kafelek_wewnatrz_kafelka_a_nie_na_calej_stronie():
    """Dopisane ponad plan. Szukanie ciała kafelka na CAŁEJ stronie trafia
    w pierwszy pasujący węzeł — przy dwóch kafelkach tego samego typu (albo
    podglądzie dającym chwilowo dwa te same klucze) drugi rysowałby się
    w pierwszym."""
    zrodlo = js_bez_komentarzy()
    assert "korzen.querySelector('[data-cialo=" not in zrodlo
    assert "getElementById('an-wykres-" not in zrodlo


def test_zmiana_selektora_nie_zapisuje_ukladu():
    """Rozstrzygniecie uzytkownika: „Chwilowe zerkniecie, po odswiezeniu wraca".
    Obsluga selektora nie ma prawa wolac zapisu."""
    zrodlo = js_bez_komentarzy()
    poczatek = zrodlo.index('function podepnijSelektory')
    cialo = zrodlo[poczatek:poczatek + 1400]
    assert 'zapiszUklad' not in cialo


def test_siatka_jest_w_osobnym_szablonie():
    """Ten sam fragment renderuje strona i endpoint /api/siatka (Zadanie 8).
    Dwie petle po tym samym ukladzie rozjechalyby sie przy pierwszej zmianie."""
    sciezka = os.path.join(KORZEN, 'modules', 'reports', 'templates',
                           'analiza', '_siatka.html')
    assert os.path.exists(sciezka)
    with open(sciezka, encoding='utf-8') as plik:
        tresc = plik.read()
    assert 'an-siatka' in tresc and 'for inst in uklad' in tresc
    with open(os.path.join(KORZEN, 'modules', 'reports', 'templates',
                           'analiza', 'dashboard.html'), encoding='utf-8') as plik:
        strona = plik.read()
    assert "include 'analiza/_siatka.html'" in strona
    assert 'for inst in uklad' not in strona, 'druga petla po ukladzie w dashboard.html'
