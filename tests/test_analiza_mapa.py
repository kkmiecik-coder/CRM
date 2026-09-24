# -*- coding: utf-8 -*-
"""Mapa wojewodztw na karcie „Sprzedaz netto wedlug: Wojewodztwo".

Trzy rzeczy, ktorych ten plik pilnuje.

1. ODWZOROWANIE IDENTYFIKATOROW. Ksztalty SVG maja `id` bez polskich znakow
   i mala litera („slaskie"), a baza trzyma nazwy kanoniczne z ogonkami
   („Slaskie"). Rozjazd po ktorejkolwiek stronie daje wojewodztwo biale na
   mapie mimo sprzedazy w tabeli — i nic tego nie krzyczy.

2. AGREGATY. Objetosc wyklucza uslugi, netto idzie z pozycji, liczba zamowien
   i klientow z zamowienia, a zlecenia produkcyjne dochodza zlaczeniem
   zewnetrznym, ktore NIE MOZE powielic pozycji.

3. WSPOLNY FRAGMENT. Sciezki mieszkaja w jednym pliku i wlacza je zarowno
   dashboard, jak i modal STAREJ zakladki. Stara szuka obszarow przez
   document.getElementById(id) (reports.js), wiec identyfikatory i wezly
   <text id="text-*"> musza tam zostac nietkniete.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from decimal import Decimal

import pytest
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import reports_bp
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.reports.utils import PostcodeToStateMapper

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)


# LONGTEXT (dialekt MySQL) na SQLite — ten sam szim i ten sam powod co
# w tests/test_analiza_api.py: bez niego create_all wywala sie CompileError.
@compiles(LONGTEXT, 'sqlite')
def _longtext_jako_text(typ, kompilator, **kw):
    return 'TEXT'


from modules.production.models import ProductionOrder  # noqa: E402,F401
from modules.users.models import User  # noqa: E402
from modules.clients.models import Client  # noqa: E402,F401
import modules.quotes.models  # noqa: E402,F401
from modules.quotes.models import QuoteStatus  # noqa: E402

from modules.reports.models_uklad import UkladDashboardu  # noqa: E402

_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    SalesClient, SalesOrder, SalesOrderItem, ProductionOrder,
    # Od Planu D /api/analytics i /analiza czytaja uklad uzytkownika z bazy.
    UkladDashboardu,
)]

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATYKA_PRODUKCJI = os.path.join(KORZEN, 'modules', 'production', 'static')
SZABLONY = os.path.join(KORZEN, 'modules', 'reports', 'templates')
SCIEZKA_FRAGMENTU = os.path.join(SZABLONY, 'analiza', '_mapa_polski.html')
SCIEZKA_MODALA = os.path.join(SZABLONY, 'voivodeships_modal.html')
SCIEZKA_CSS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'css', 'analiza.css')
SCIEZKA_JS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'analiza.js')

OKRES = 'od=2026-09-01&do=2026-09-30'


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
    # Nazwa blueprintu MUSI brzmiec 'production' — dashboard.html wola
    # url_for('production.static', ...) po Chart.js (patrz test_analiza_widok).
    produkcja = Blueprint('production', __name__, static_folder=STATYKA_PRODUKCJI,
                          static_url_path='/production/static')
    app.register_blueprint(produkcja, url_prefix='/production')
    app.jinja_loader = ChoiceLoader([
        DictLoader({'sidebar/sidebar.html': '<nav data-sidebar-zaslepka></nav>'}),
        app.jinja_loader,
    ])
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
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
def strona(client):
    odpowiedz = client.get('/reports/analiza')
    assert odpowiedz.status_code == 200
    return odpowiedz.get_data(as_text=True)


def _klient(ident):
    db.session.add(SalesClient(id=ident, display_name=f'Klient {ident}',
                               orders_count=1, lifetime_net=Decimal('0')))


def _zamowienie(bl_id, wojewodztwo, pozycje, klient=None, dzien=date(2026, 9, 3)):
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien,
                     delivery_state=wojewodztwo, client_id=klient,
                     balance_due=Decimal('1000.00'), order_source='shop',
                     caretaker='Łukasz Próbny', current_status='Nowe',
                     delivery_method='Kurier', delivery_cost=Decimal('100.00'))
    db.session.add(zam)
    db.session.flush()
    for netto, objetosc, grupa in pozycje:
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal(netto), total_volume=Decimal(objetosc),
            group_type=grupa, wood_species='dąb', technology='lity',
            wood_class='A/B', finish_state='surowy', quantity=1))
    return zam


def _zlecenie(bl_id, numer='W/1'):
    db.session.add(ProductionOrder(baselinker_order_id=bl_id,
                                   internal_order_number=numer))


# Klucz karty województw w payloadzie. Od Planu D karty są kluczowane
# INSTANCJĄ (`typ:wymiar`), bo ten sam typ może stać na pulpicie kilka razy.
KARTA_WOJEWODZTW = 'wojewodztwo:delivery_state'


def _mapa(client, zapytanie=OKRES, klucz=KARTA_WOJEWODZTW):
    dane = client.get('/reports/api/analytics?' + zapytanie).get_json()
    return dane['karty'][klucz].get('mapa'), dane


def _obszar(mapa, identyfikator):
    return [o for o in mapa['obszary'] if o['id'] == identyfikator][0]


# --- odwzorowanie identyfikatorow -------------------------------------------

def test_jest_dokladnie_szesnascie_obszarow():
    from modules.reports.analytics import IDENTYFIKATORY_WOJEWODZTW, WOJEWODZTWA

    assert len(IDENTYFIKATORY_WOJEWODZTW) == 16
    assert len(set(IDENTYFIKATORY_WOJEWODZTW)) == 16
    assert set(WOJEWODZTWA) == set(IDENTYFIKATORY_WOJEWODZTW)


def test_nazwy_wojewodztw_ida_z_rejestru_a_nie_z_trzeciej_listy():
    """Mapa nazw ma JEDNO zrodlo: STATE_NORMALIZATION w modules/reports/utils.py.

    To ta sama mapa, ktorej uzywa import z BaseLinkera przy zapisie wartosci
    do `sales_orders.delivery_state`. Przepisana osobno dla mapy rozjechalaby
    sie przy pierwszej poprawce po tamtej stronie, a objawem byloby
    wojewodztwo biale na mapie mimo sprzedazy w tabeli.
    """
    from modules.reports.analytics import IDENTYFIKATORY_WOJEWODZTW, WOJEWODZTWA

    for klucz in IDENTYFIKATORY_WOJEWODZTW:
        assert klucz in PostcodeToStateMapper.STATE_NORMALIZATION, (
            f'identyfikator SVG „{klucz}" nie ma odpowiednika w '
            f'STATE_NORMALIZATION — mapa go nie rozpozna')
        assert WOJEWODZTWA[klucz] == PostcodeToStateMapper.STATE_NORMALIZATION[klucz]


def test_odwzorowanie_dziala_w_obie_strony():
    from modules.reports.analytics import (
        IDENTYFIKATORY_PO_NAZWIE, IDENTYFIKATORY_WOJEWODZTW, WOJEWODZTWA,
    )

    # Bijekcja: dwa identyfikatory o tej samej nazwie znaczylyby, ze droga
    # powrotna gubi jeden z obszarow.
    assert len(IDENTYFIKATORY_PO_NAZWIE) == 16
    for klucz in IDENTYFIKATORY_WOJEWODZTW:
        assert IDENTYFIKATORY_PO_NAZWIE[WOJEWODZTWA[klucz]] == klucz


@pytest.mark.parametrize('zapis, oczekiwany', [
    ('Mazowieckie', 'mazowieckie'),
    ('mazowieckie', 'mazowieckie'),
    ('Śląskie', 'slaskie'),
    ('slaskie', 'slaskie'),
    ('ŚLĄSKIE', 'slaskie'),
    ('Warmińsko-Mazurskie', 'warminsko-mazurskie'),
    ('warminsko-mazurskie', 'warminsko-mazurskie'),
    ('Łódzkie', 'lodzkie'),
    ('  Małopolskie  ', 'malopolskie'),
])
def test_rozpoznaje_wojewodztwo_zapisane_na_rozne_sposoby(zapis, oczekiwany):
    from modules.reports.analytics import identyfikator_wojewodztwa

    assert identyfikator_wojewodztwa(zapis) == oczekiwany


@pytest.mark.parametrize('zapis', [None, '', '   ', 'Dol', 'Zagranica', 'Berlin'])
def test_wartosc_nierozpoznana_nie_trafia_na_zaden_obszar(zapis):
    """„Dol" siedzi w bazie naprawde — uciety zapis z BaseLinkera. Wartosc,
    ktorej nie da sie rozpoznac, MUSI wyjsc poza mape, a nie wpasc do
    przypadkowego wojewodztwa."""
    from modules.reports.analytics import identyfikator_wojewodztwa

    assert identyfikator_wojewodztwa(zapis) is None


# --- wspolny fragment SVG ---------------------------------------------------

def test_fragment_niesie_szesnascie_sciezek_w_kolejnosci_z_analytics():
    from modules.reports.analytics import IDENTYFIKATORY_WOJEWODZTW

    tresc = open(SCIEZKA_FRAGMENTU, encoding='utf-8').read()
    znalezione = re.findall(r"\{\{ obszar\('([a-z-]+)',", tresc)
    assert znalezione == list(IDENTYFIKATORY_WOJEWODZTW)


def test_nazwy_w_fragmencie_zgadzaja_sie_z_odwzorowaniem():
    """`data-name` w SVG to nazwa dla czlowieka. Rozjazd z WOJEWODZTWA
    znaczylby, ze dymek podpisuje obszar inaczej, niz nazywa go baza."""
    from modules.reports.analytics import WOJEWODZTWA

    tresc = open(SCIEZKA_FRAGMENTU, encoding='utf-8').read()
    pary = re.findall(r"\{\{ obszar\('([a-z-]+)', '([^']+)',", tresc)
    assert {klucz: nazwa for klucz, nazwa in pary} == WOJEWODZTWA


def test_fragment_nie_zawiera_wlasnego_svg():
    """Wrapper nalezy do strony: stara zakladka rysuje mape na 800x600
    z podpisami w srodku, dashboard w cwiartce rzedu i bez podpisow."""
    tresc = open(SCIEZKA_FRAGMENTU, encoding='utf-8').read()
    # Komentarze Jinjy odcinamy — one o <svg> tylko MOWIA (wyjasniaja, czemu
    # go tu nie ma), a chodzi o to, czy fragment go RYSUJE.
    bez_komentarzy = re.sub(r'\{#.*?#\}', '', tresc, flags=re.S)
    assert '<svg' not in bez_komentarzy


def test_stara_zakladka_wlacza_ten_sam_fragment_zamiast_kopii():
    tresc = open(SCIEZKA_MODALA, encoding='utf-8').read()
    assert "include 'analiza/_mapa_polski.html'" in tresc
    # Ani jednej sciezki przepisanej na miejscu — inaczej poprawka geometrii
    # w jednym miejscu nie dochodzi do drugiego.
    assert '<path id=' not in tresc


def test_modal_starej_zakladki_nadal_ma_komplet_obszarow_i_podpisow(app):
    """Kontrakt z reports.js: klasa VoivodeshipsManager szuka obszarow przez
    document.getElementById(id) i wpisuje metry szescienne w <text id="text-*">.
    Brak ktoregokolwiek wezla = ciche nic (getElementById zwraca null)."""
    from modules.reports.analytics import IDENTYFIKATORY_WOJEWODZTW

    with app.app_context():
        from flask import render_template
        wynik = render_template('voivodeships_modal.html')

    assert 'class="poland-map"' in wynik
    for klucz in IDENTYFIKATORY_WOJEWODZTW:
        assert f'<path id="{klucz}"' in wynik, f'stara mapa stracila obszar {klucz}'
        assert f'id="text-{klucz}"' in wynik, f'stara mapa stracila podpis {klucz}'
    # Obszary w modalu NIE sa fokusowalne — to dashboardowa mapa ma dymek.
    assert 'tabindex' not in wynik


# --- agregaty ---------------------------------------------------------------

def test_kazde_wojewodztwo_wraca_nawet_bez_zamowien(client, app):
    """Dziura w slowniku zmusilaby przegladarke do zgadywania, co narysowac."""
    from modules.reports.analytics import IDENTYFIKATORY_WOJEWODZTW

    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1)
        db.session.commit()

    mapa, _ = _mapa(client)
    assert [o['id'] for o in mapa['obszary']] == list(IDENTYFIKATORY_WOJEWODZTW)
    puste = _obszar(mapa, 'opolskie')
    assert puste['ma_dane'] is False
    assert puste['netto'] == 0 and puste['zamowienia'] == 0


def test_komplet_statystyk_jednego_wojewodztwa(client, app):
    with app.app_context():
        _klient(1)
        _klient(2)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar'),
                                       ('500.00', '0.25', 'towar')], klient=1)
        _zamowienie(2, 'Mazowieckie', [('300.00', '0.10', 'towar')], klient=2)
        # Trzecie zamowienie tego samego klienta — liczba klientow ma zostac 2.
        _zamowienie(3, 'Mazowieckie', [('200.00', '0.05', 'towar')], klient=2)
        _zlecenie(1)
        _zlecenie(2)
        db.session.commit()

    mapa, _ = _mapa(client)
    maz = _obszar(mapa, 'mazowieckie')
    assert maz['nazwa'] == 'Mazowieckie'
    assert maz['netto'] == 2000
    assert maz['objetosc'] == pytest.approx(0.90)
    assert maz['zamowienia'] == 3
    assert maz['klienci'] == 2
    assert maz['w_produkcji'] == 2


def test_objetosc_wyklucza_uslugi(client, app):
    """Suszenie uslugowe ma metry szescienne w polu ilosci — bez wykluczenia
    jedna usluga przewraca skale calej mapy (na produkcji: 273 m3 zamiast 63
    w kubelku zamowien bez wojewodztwa)."""
    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar'),
                                       ('400.00', '88.00', 'usługa')], klient=1)
        db.session.commit()

    mapa, _ = _mapa(client)
    maz = _obszar(mapa, 'mazowieckie')
    assert maz['objetosc'] == pytest.approx(0.50)
    # Netto uslugi ZOSTAJE — usluga tez jest sprzedaza.
    assert maz['netto'] == 1400


def test_zlecenie_produkcyjne_nie_powiela_netto(client, app):
    """Zlaczenie zewnetrzne z prod_orders stoi na tym, ze
    `baselinker_order_id` jest tam UNIQUE. Gdyby przestalo byc prawda,
    SUM(value_net) zaczalby zawyzac — dokladnie ten blad, ktory Plan A
    zamknal po stronie salda."""
    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar'),
                                       ('1000.00', '0.50', 'towar')], klient=1)
        _zlecenie(1)
        db.session.commit()

    mapa, _ = _mapa(client)
    maz = _obszar(mapa, 'mazowieckie')
    assert maz['netto'] == 2000
    assert maz['w_produkcji'] == 1


def test_zamowienia_bez_wojewodztwa_sa_widoczne_poza_mapa(client, app):
    """296 zamowien na calej bazie (691 103 zl) nie ma wojewodztwa. Bez tego
    wiersza suma mapy nie zgadza sie z KPI i nikt nie wie dlaczego."""
    with app.app_context():
        _klient(1)
        _klient(2)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1)
        _zamowienie(2, '', [('700.00', '0.30', 'towar')], klient=2)
        _zamowienie(3, None, [('300.00', '0.10', 'towar')], klient=2)
        db.session.commit()

    mapa, _ = _mapa(client)
    poza = {p['etykieta']: p for p in mapa['poza_mapa']}
    # NULL i pusty napis znacza to samo i scalaja sie w jeden wiersz.
    assert list(poza) == ['(brak)']
    assert poza['(brak)']['netto'] == 1000
    assert poza['(brak)']['zamowienia'] == 2


def test_nazwa_nierozpoznana_ma_wlasny_wiersz_poza_mapa(client, app):
    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1)
        _zamowienie(2, 'Dol', [('154.44', '0.01', 'towar')], klient=1)
        db.session.commit()

    mapa, _ = _mapa(client)
    etykiety = [p['etykieta'] for p in mapa['poza_mapa']]
    assert 'Dol' in etykiety, 'ucieta nazwa z BaseLinkera zniknela bez sladu'
    # Zadne wojewodztwo nie dostalo tych pieniedzy po cichu.
    assert sum(o['netto'] for o in mapa['obszary']) == 1000


def test_mapa_respektuje_okres(client, app):
    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1,
                    dzien=date(2026, 9, 3))
        _zamowienie(2, 'Mazowieckie', [('9999.00', '5.00', 'towar')], klient=1,
                    dzien=date(2026, 8, 3))
        db.session.commit()

    mapa, _ = _mapa(client)
    assert _obszar(mapa, 'mazowieckie')['netto'] == 1000


# --- skala kolorow ----------------------------------------------------------

def test_najwiekszy_obszar_dostaje_najwyzszy_stopien(client, app):
    from modules.reports.analiza_service import POZIOMY_MAPY

    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('10000.00', '5.00', 'towar')], klient=1)
        _zamowienie(2, 'Opolskie', [('10.00', '0.01', 'towar')], klient=1)
        db.session.commit()

    mapa, _ = _mapa(client)
    assert mapa['poziomy'] == POZIOMY_MAPY
    assert _obszar(mapa, 'mazowieckie')['poziom'] == POZIOMY_MAPY
    # Najmniejsza DODATNIA wartosc nadal ma byc widoczna jako stopien 1,
    # a nie zlac sie z tlem przez zaokraglenie w dol.
    assert _obszar(mapa, 'opolskie')['poziom'] == 1


def test_zero_odroznia_sie_od_braku_danych(client, app):
    """Wojewodztwo z zamowieniami na zero zlotych to co innego niz
    wojewodztwo, do ktorego nigdy nic nie pojechalo."""
    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1)
        _zamowienie(2, 'Opolskie', [('0.00', '0.00', 'towar')], klient=1)
        db.session.commit()

    mapa, _ = _mapa(client)
    zerowe = _obszar(mapa, 'opolskie')
    puste = _obszar(mapa, 'lubuskie')
    assert zerowe['ma_dane'] is True and zerowe['poziom'] == 0
    assert puste['ma_dane'] is False


def test_kolor_skaluje_sie_po_tej_samej_mierze_co_naglowek_kolumny(client, app):
    """NIEZMIENNIK: kartogram maluje to, co podpisuje naglowek karty.
    Karty wojewodztw i dostawy mialy juz raz slupek niosacy netto i liczbe
    obok bedaca objetoscia — tutaj ta sama klasa bledu wygladalaby tak, ze
    mapa jest pomalowana metrami, a nad nia stoi „NETTO zl"."""
    from modules.reports.analiza_service import KOLUMNY_KART

    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1)
        db.session.commit()

    mapa, _ = _mapa(client)
    assert mapa['miara'] == KOLUMNY_KART['wojewodztwo'][0] == 'netto'


# --- kontrakt payloadu ------------------------------------------------------

def test_mapa_jest_tylko_dla_wymiaru_opisujacego_wojewodztwa(client, app):
    """Selektor wymiaru na karcie zostaje (anatomia karty z makiety), wiec
    po przelaczeniu go na „Opiekun" mapa Polski opisywalaby handlowcow."""
    from modules.reports.analiza_service import WYMIAR_MAPY, DOMYSLNE_WYMIARY

    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1)
        db.session.commit()

    assert DOMYSLNE_WYMIARY['wojewodztwo'] == WYMIAR_MAPY
    mapa, _ = _mapa(client)
    assert mapa is not None

    # Od Planu D wymiar karty jest częścią ZAPISANEGO układu, a nie adresu.
    odpowiedz = client.post('/reports/api/uklad', json={'uklad': [
        {'typ': 'wojewodztwo', 'wymiar': 'caretaker'}]})
    assert odpowiedz.status_code == 200
    inna, dane = _mapa(client, klucz='wojewodztwo:caretaker')
    assert inna is None
    # ...a karta nadal ma czym rysowac slupki.
    assert dane['karty']['wojewodztwo:caretaker']['wiersze']


def test_dymek_ma_komplet_miar_z_jednostkami(client, app):
    """Kazda liczba w dymku ma byc podpisana, a jednostka ma przyjsc
    z rejestru miar — nie z listy wpisanej w analiza.js ani w szablonie."""
    from modules.reports.analiza_service import ETYKIETY_MIAR, JEDNOSTKI_MIAR

    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1)
        db.session.commit()

    mapa, dane = _mapa(client)
    nazwy = [m['nazwa'] for m in mapa['miary']]
    assert nazwy == ['netto', 'objetosc', 'zamowienia', 'klienci', 'w_produkcji']
    for miara in mapa['miary']:
        assert miara['etykieta'] == ETYKIETY_MIAR[miara['nazwa']]
        assert dane['jednostki'][miara['nazwa']] == JEDNOSTKI_MIAR[miara['nazwa']]
        assert dane['jednostki'][miara['nazwa']]
    # Liczba miejsc dziesietnych tez idzie z serwera — inaczej przegladarka
    # musialaby trzymac wlasna regule „objetosc ma dwa miejsca".
    assert {m['nazwa']: m['miejsca'] for m in mapa['miary']}['objetosc'] == 2


def test_jednostki_miar_mapy_sa_po_polsku(client, app):
    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1)
        db.session.commit()

    jednostki = client.get('/reports/api/analytics?' + OKRES).get_json()['jednostki']
    assert jednostki['w_produkcji'] == 'szt.'
    assert jednostki['klienci'] == 'szt.'


def test_etykieta_w_produkcji_nie_powiela_etykiety_z_rejestru_pol():
    """NIEZMIENNIK: ta sama etykieta znaczy wszedzie to samo.

    „W produkcji" to liczba zlecen w `prod_orders` dowiazanych do zamowien
    okresu — nie jest zadna kolumna `sales_orders`. Gdyby brzmiala tak samo
    jak pole rejestru, ktos zestawilby ze soba dwie liczby o roznym
    znaczeniu (ta sama pulapka, co „Kanal sprzedazy" na karcie lejka).
    """
    from modules.reports.analiza_service import ETYKIETY_MIAR
    from modules.reports.fields import POLA

    etykiety_rejestru = {pole.etykieta for pole in POLA.values()}
    assert ETYKIETY_MIAR['w_produkcji'] not in etykiety_rejestru


def test_segment_porownawczy_dochodzi_do_mapy(client, app):
    """Karta wojewodztw jest w KARTY_Z_SEGMENTEM. Mapa bez drugiej serii
    wygladalaby po wlaczeniu segmentu identycznie jak bez niego — to
    znalezisko z przegladu Zadania 10, powtorzone tu celowo."""
    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1)
        zam = _zamowienie(2, 'Mazowieckie', [('400.00', '0.20', 'towar')], klient=1)
        zam.order_source = 'allegro'
        _zamowienie(3, '', [('100.00', '0.05', 'towar')], klient=1)
        db.session.commit()

    mapa, dane = _mapa(client, OKRES + '&porownanie=order_source:shop')
    drugie = dane['porownanie']['mapa']

    # Wyrownanie CO DO INDEKSU — dymek dopisuje druga liczbe obok pierwszej
    # i musi wiedziec, ktora do ktorej.
    assert len(drugie['obszary']) == len(mapa['obszary'])
    assert len(drugie['poza_mapa']) == len(mapa['poza_mapa'])
    maz = [i for i, o in enumerate(mapa['obszary']) if o['id'] == 'mazowieckie'][0]
    assert mapa['obszary'][maz]['netto'] == 1400
    assert drugie['obszary'][maz]['netto'] == 1000    # samo „shop"
    assert drugie['poza_mapa'][0]['netto'] == 100


def test_bez_segmentu_nie_ma_drugiej_serii(client, app):
    with app.app_context():
        _klient(1)
        _zamowienie(1, 'Mazowieckie', [('1000.00', '0.50', 'towar')], klient=1)
        db.session.commit()

    assert client.get('/reports/api/analytics?' + OKRES).get_json()['porownanie'] is None


# --- widok ------------------------------------------------------------------

# Od Planu D kafelek wojewodztw moze stac na pulpicie kilka razy, wiec
# identyfikator sciezki niesie PREFIKS kafelka (klucz instancji z dwukropkiem
# zamienionym na myslnik), a analiza.js szuka obszaru po `data-obszar`.
PREFIKS_MAPY = KARTA_WOJEWODZTW.replace(':', '-') + '-'


def _kafelek_wojewodztw(strona):
    """Znacznik kafelka wojewodztw z ukladu domyslnego — od sekcji do jej konca."""
    return strona.split(f'data-klucz="{KARTA_WOJEWODZTW}"')[1].split('</section>')[0]


def test_karta_wojewodztw_ma_mape_a_nie_druga_kopie_sciezek(strona):
    assert f'data-mapa="{KARTA_WOJEWODZTW}"' in strona
    assert strona.count(f'<path id="{PREFIKS_MAPY}mazowieckie"') == 1
    assert strona.count('data-obszar="mazowieckie"') == 1


def test_obszary_na_dashboardzie_sa_fokusowalne_i_opisane(strona):
    """Dymek wylacznie na :hover wyklucza klawiature i tablet."""
    from modules.reports.analytics import WOJEWODZTWA

    for klucz, nazwa in WOJEWODZTWA.items():
        wzorzec = re.compile(
            r'<path id="' + re.escape(PREFIKS_MAPY + klucz) + r'"[^>]*'
            r'data-obszar="' + re.escape(klucz) + r'"[^>]*tabindex="0"[^>]*'
            r'aria-label="' + re.escape(nazwa) + r'"', re.S)
        assert wzorzec.search(strona), f'obszar {klucz} bez fokusu albo bez nazwy'


def test_dymek_stoi_poza_karta_bo_karta_obcina_tresc(strona):
    """.an-karta ma overflow: hidden — dymek w srodku karty bylby przyciety
    do jej ramki przy wojewodztwach z krawedzi mapy."""
    assert 'id="an-mapa-dymek"' in strona
    assert 'an-mapa-dymek' not in _kafelek_wojewodztw(strona)


def test_dymek_jest_schowany_zanim_ktos_najedzie(strona):
    dymek = strona.split('id="an-mapa-dymek"')[1].split('>')[0]
    assert 'hidden' in dymek
    assert 'role="tooltip"' in strona


def test_legenda_odroznia_brak_danych_od_stopnia_skali(strona):
    assert strona.count('an-mapa__probka--p') == 5
    assert 'an-mapa__probka--brak' in strona
    assert 'bez danych' in strona


def test_karta_zachowuje_naglowek_selektor_i_jedno_wyjscie(strona):
    """Anatomia karty z makiety zostaje: naglowek, selektor wymiaru, tresc
    i JEDNO wyjscie w stopce. Mapa zmienia tylko tresc.

    Tekst wyjscia NIE jest juz „Otwórz mapę województw" z makiety — makieta
    powstala, gdy ta karta byla lista poziomych slupkow, a jedyna mapa
    wojewodztw na stronie byla w modalu starej zakladki pod tym linkiem.
    Od kartogramu (22.09) karta SAMA jest mapa wojewodztw, wiec ten sam
    podpis pod nia brzmialby, jakby otwieral te sama mape drugi raz. Link
    prowadzi do INNEJ mapy — metrow szesciennych z modulu produkcji — wiec
    dostal tekst, ktory to mowi wprost."""
    karta = _kafelek_wojewodztw(strona)
    assert 'Sprzedaż netto według:' in karta
    assert f'data-selektor="{KARTA_WOJEWODZTW}"' in karta
    assert karta.count('an-karta__stopka') == 1
    assert 'Otwórz mapę produkcji' in karta


def test_selektor_karty_wojewodztw_nadal_ma_opakowanie(strona):
    """Bez .an-sel-opak przezroczysty <select> z inset: 0 rozlewa sie na cale
    okno i cala zakladka przestaje byc klikalna. Zdarzylo sie tu juz raz."""
    from bs4 import BeautifulSoup

    zupa = BeautifulSoup(strona, 'html.parser')
    wybor = zupa.select_one(f'select[data-selektor="{KARTA_WOJEWODZTW}"]')
    assert wybor is not None
    assert 'an-sel-opak' in (wybor.parent.get('class') or [])


def test_tabela_poza_mapa_jest_schowana_dopoki_nie_ma_wierszy(strona):
    tabela = strona.split(f'data-poza-mapa="{KARTA_WOJEWODZTW}"')[1].split('>')[0]
    assert 'hidden' in tabela


def test_kolumny_tabeli_poza_mapa_sa_podpisane_jednostka(strona):
    from modules.reports.analiza_service import JEDNOSTKI_MIAR

    naglowek = strona.split(f'data-poza-mapa="{KARTA_WOJEWODZTW}"')[1].split('</thead>')[0]
    assert 'Poza mapą' in naglowek
    assert JEDNOSTKI_MIAR['netto'] in naglowek
    assert JEDNOSTKI_MIAR['zamowienia'] in naglowek


# --- style ------------------------------------------------------------------

def _css():
    return open(SCIEZKA_CSS, encoding='utf-8').read()


def test_skala_ma_wszystkie_stopnie_plus_brak_danych():
    css = _css()
    for poziom in range(0, 6):
        assert f'path[data-poziom="{poziom}"]' in css, f'brak koloru stopnia {poziom}'
    assert 'path[data-poziom="brak"]' in css


def test_skala_nie_uzywa_czerwieni():
    """Czerwien na tej zakladce jest zarezerwowana dla bledow."""
    css = _css()
    blok = css.split('/* ===== MAPA WOJEWODZTW')[1].split('/* ===== EKSPLORATOR')[0]
    for zakazany in ('var(--bad)', 'var(--bad-bg)', 'var(--bad-ink)'):
        assert zakazany not in blok
    # Skala jest SEKWENCYJNA, jednoodcieniowa: konczy sie akcentem marki
    # i jego ciemniejsza odmiana, a nie kolorami z innych rodzin.
    assert 'fill: var(--accent); }' in blok
    assert 'fill: var(--accent-dark); }' in blok
    for tecza in ('var(--c-teal)', 'var(--c-purple)', 'var(--ok)'):
        assert f'path[data-poziom' not in blok.split(tecza)[0][-60:]


def test_dymek_nie_lapie_klikniec():
    """Przezroczysta warstwa fixed, ktora lapie kliknięcia, to dokladnie ta
    pulapka, przez ktora cala ta zakladka byla raz nieklikalna."""
    blok = _css().split('.an-mapa__dymek {')[1].split('}')[0]
    assert 'pointer-events: none' in blok
    assert 'position: fixed' in blok
    # Schowany dymek MUSI miec display: none, inaczej elementFromPoint
    # zwracalby go mimo atrybutu hidden (klasa ustawia display: block).
    assert '.an-mapa__dymek[hidden] { display: none; }' in _css()


def test_mapa_ma_stala_wysokosc_zeby_nie_rozpychac_rzedu():
    """Z wysokoscia liczona od szerokosci karty mapa brala 602 px przy dwoch
    kolumnach i ciagnela za soba sasiadke z tego samego rzedu siatki
    (zmierzone: karta „Klienci" 294 px -> 830 px)."""
    css = _css()
    assert '--wys-mapa:' in css
    assert 'height: var(--wys-mapa)' in css


def test_cyfry_w_dymku_sa_monospacem_a_jednostka_tekstem():
    blok = _css().split('.an-mapa__dymek-liczba {')[1].split('}')[0]
    assert "'IBM Plex Mono'" in blok
    assert '.an-mapa__dymek-liczba .an-jednostka' in _css()


# --- javascript -------------------------------------------------------------

def _js():
    return open(SCIEZKA_JS, encoding='utf-8').read()


def test_js_nie_liczy_stopnia_skali_tylko_przepisuje_go_z_payloadu():
    js = _js()
    fragment = js.split('function rysujMapeWojewodztw')[1].split('function rysujPozaMapa')[0]
    assert "obszar.ma_dane ? String(obszar.poziom) : 'brak'" in fragment
    # Zadnego dzielenia przez maksimum po stronie przegladarki — skale
    # liczy serwer, tak samo jak udzialy i zmiany procentowe.
    assert 'maks' not in fragment


def test_js_pokazuje_dymek_takze_z_klawiatury_i_po_dotknieciu():
    fragment = _js().split('function podepnijMape')[1].split('function rysujMapeWojewodztw')[0]
    for zdarzenie in ('mousemove', 'focusin', 'click'):
        assert f"addEventListener('{zdarzenie}'" in fragment
    # Tapniecie PRZYPINA dymek (na tablecie nie ma zjechania kursorem),
    # a Escape i klikniecie poza mapa go zamykaja.
    assert "zdarzenie.key === 'Escape'" in fragment
    assert 'dymekPrzypiety' in fragment


def test_js_opisuje_obszar_dla_czytnika_ekranu():
    fragment = _js().split('function opisObszaru')[1].split('function wypelnijDymek')[0]
    assert 'obszar.nazwa' in fragment
    assert 'mapaMiary.forEach' in fragment
    assert "aria-label', opisObszaru(" in _js()


def test_js_nie_wstawia_tresci_dymka_przez_innerhtml():
    """Nazwy wojewodztw i etykiety „poza mapa" pochodza z BaseLinkera —
    to tekst z zewnetrznego systemu na stronie zalogowanego uzytkownika."""
    for funkcja in ('wypelnijDymek', 'rysujPozaMapa'):
        fragment = _js().split('function ' + funkcja)[1].split('\n  }')[0]
        assert 'innerHTML' not in fragment


def test_js_kasuje_slupki_gdy_karta_pokazuje_mape():
    """Wiersze szkieletu (i wiersze poprzedniego wymiaru) musza zniknac,
    zamiast zostac nad mapa."""
    fragment = _js().split('var mapaWojewodztw = rysujMapeWojewodztw')[1][:700]
    assert 'wiersze: []' in fragment
