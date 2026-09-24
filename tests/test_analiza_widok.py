# -*- coding: utf-8 -*-
"""Widok dashboardu: szkielet ladowania i jego kontrakt z JavaScriptem.

Sidebar jest podmieniony na zaslepke przez DictLoader. Powod: prawdziwy
modules/sidebar/sidebar.html wola url_for do kilkunastu blueprintow i w
minimalnym Flasku wywalilby sie BuildError-em, ktory nie ma nic wspolnego
z tym, co ten plik testuje. Spojnosc samego sidebara pilnuje Zadanie 13.

Blueprint `production` jest natomiast rejestrowany NAPRAWDE, bo szablon
dashboardu wola url_for('production.static', ...) po Chart.js. Bez niego
url_for rzuca BuildError w trakcie renderowania, app.testing jest domyslnie
False, wiec test_client() dostaje 500 zamiast wyjatku — i pada CALY blok
testow strony, bez zadnej wskazowki, co jest nie tak. Ten sam gotcha i to
samo rozwiazanie co w tests/test_monitory_krawedzie.py:85-90.
"""
import json
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
from modules.reports.fields import POLA, wymiary
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
# prod_orders jest po drugiej stronie lejka wycen (stopien „W realizacji"),
# wiec tabela MUSI istniec w bazie testowej — inaczej kazdy test dotykajacy
# /api/analytics wywala sie na „no such table: prod_orders".
# `prod_orders.shipping_label_base64` jest kolumna typu LONGTEXT (dialekt
# MySQL), a SQLite nie umie takiej skompilowac — `create_all` wywala sie
# CompileError, zanim ruszy pierwszy test. Uczymy wiec kompilator SQLite
# czytac LONGTEXT jako TEXT. Szim jest TESTOWY: na produkcji kolumna ma
# zostac LONGTEXT-em, bo trzyma etykiete kurierska w base64.
@compiles(LONGTEXT, 'sqlite')
def _longtext_jako_text(typ, kompilator, **kw):
    return 'TEXT'

from modules.production.models import ProductionOrder  # noqa: F401 — rejestr mapperów
from modules.users.models import User
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów
from modules.quotes.models import QuoteStatus

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KATALOG_FONTOW = os.path.join(KORZEN, 'modules', 'reports', 'static', 'vendor', 'fonts')
SCIEZKA_CSS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'css', 'analiza.css')
STATYKA_PRODUKCJI = os.path.join(KORZEN, 'modules', 'production', 'static')

# Link do Poppinsa — dokladnie ten sam, ktorego uzywa
# modules/reports/templates/reports.html i dwanascie innych szablonow.
LINK_POPPINS = ('https://fonts.googleapis.com/css2?'
                'family=Poppins:wght@300;400;500;600;700&display=swap')

from modules.reports.models_uklad import UkladDashboardu  # noqa: E402
from modules.reports.uklad import KATALOG, UKLAD_DOMYSLNY, Instancja  # noqa: E402

_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    SalesClient, SalesOrder, SalesOrderItem, ProductionOrder,
    # Od Planu D /analiza i /api/analytics czytaja uklad uzytkownika z bazy.
    UkladDashboardu,
)]

# Od Planu D kafelek identyfikuje KLUCZ INSTANCJI (`typ:wymiar`), nie typ —
# ten sam typ moze stac na pulpicie kilka razy. Klucze bierzemy z ukladu
# domyslnego, nie wpisujemy z pamieci.
KLUCZE_KART = [i.klucz for i in UKLAD_DOMYSLNY]

# PULPIT PELNY: kazdy typ katalogu raz, w swoim wymiarze domyslnym, w kolejnosci
# sprzed partii E. Od punktu E1 karty „Naleznosci wedlug" nie ma w ukladzie
# domyslnym (typ zostaje w katalogu), wiec testy tej karty i testy niezmiennikow
# obejmujacych KAZDY typ (select w opakowaniu, naglowki kolumn, stopki) jada na
# tym ukladzie — inaczej po cichu przestalyby sprawdzac karte naleznosci.
UKLAD_PELNY = [Instancja(typ, KATALOG[typ].domyslny_wymiar if KATALOG[typ].wymiarowy
                         else None)
               for typ in ('kpi', 'wnioski', 'kanal', 'opiekun', 'mix', 'klienci',
                           'wojewodztwo', 'naleznosci', 'lejek', 'wykonczenie',
                           'dostawa')]
assert {i.typ for i in UKLAD_PELNY} == set(KATALOG)
# Klucz instancji kafelka danego typu (wymiar domyslny) — z pelnego ukladu,
# bo dla kafelkow ukladu domyslnego klucz jest ten sam.
KLUCZ = {i.typ: i.klucz for i in UKLAD_PELNY}


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
    # Szablon dashboardu wola url_for('production.static', ...) po Chart.js.
    # Nazwa blueprintu MUSI brzmiec 'production' — patrz docstring modulu.
    produkcja = Blueprint('production', __name__, static_folder=STATYKA_PRODUKCJI,
                          static_url_path='/production/static')
    app.register_blueprint(produkcja, url_prefix='/production')
    # Zaslepka sidebara — patrz docstring modulu.
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


@pytest.fixture()
def strona_pelna(app, client):
    """Pulpit z zapisanym UKLAD_PELNY — patrz komentarz przy tej stalej."""
    uzytkownik = User.query.filter_by(email='kontroler@woodpower.pl').one()
    db.session.add(UkladDashboardu(user_id=uzytkownik.id, uklad=[
        {'typ': i.typ, 'wymiar': i.wymiar} for i in UKLAD_PELNY]))
    db.session.commit()
    odpowiedz = client.get('/reports/analiza')
    assert odpowiedz.status_code == 200
    tresc = odpowiedz.get_data(as_text=True)
    assert re.findall(r'data-klucz="([^"]+)"', tresc) == [i.klucz for i in UKLAD_PELNY]
    return tresc


# --- fonty lokalnie ---------------------------------------------------------

@pytest.mark.parametrize('rodzina', ['IBMPlexSans', 'IBMPlexMono'])
@pytest.mark.parametrize('odmiana', ['Regular', 'Medium', 'SemiBold', 'Bold'])
def test_plik_fontu_lezy_w_repo_i_nie_jest_strona_bledu(rodzina, odmiana):
    sciezka = os.path.join(KATALOG_FONTOW, f'{rodzina}-{odmiana}.woff2')
    assert os.path.exists(sciezka), f'brak {sciezka}'
    assert os.path.getsize(sciezka) > 10000, 'plik za maly — curl zapisal strone bledu?'


def test_css_deklaruje_font_face_dla_obu_rodzin():
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    assert css.count('@font-face') >= 8
    assert "font-family: 'IBM Plex Sans'" in css
    assert "font-family: 'IBM Plex Mono'" in css


def test_css_nie_siega_do_zadnego_cdn():
    """Safari ITP blokuje jsdelivr i cdnjs, a fonty maja byc lokalne."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    for zakazane in ('fonts.googleapis.com', 'fonts.gstatic.com',
                     'cdn.jsdelivr.net', 'cdnjs.cloudflare.com', '@import'):
        assert zakazane not in css, f'analiza.css siega do {zakazane}'


# --- strona -----------------------------------------------------------------

def test_strona_ma_tytul_analiza_sprzedazowa(strona):
    assert '<title>Analiza sprzedażowa' in strona
    assert 'Analiza sprzedażowa</h1>' in strona


def test_strona_nie_laduje_zadnego_skryptu_ani_stylu_z_cdn(strona):
    """Safari ITP blokuje jsdelivr i cdnjs — krytyczny JS i CSS musi byc lokalny."""
    for zakazane in ('cdn.jsdelivr.net', 'cdnjs.cloudflare.com', 'unpkg.com'):
        assert zakazane not in strona, f'szablon siega do {zakazane}'


def test_strona_laduje_poppinsa_tym_samym_linkiem_co_reszta_crm(strona):
    """Sidebar ma wygladac identycznie jak na kazdej innej zakladce. Poppinsa
    NIE vendorujemy — decyzja uzytkownika z 21.09.2026; IBM Plex zostaje lokalny."""
    assert LINK_POPPINS in strona


def test_poppins_to_jedyny_zewnetrzny_zasob_strony(strona):
    """Zaden inny host poza Google Fonts nie ma prawa sie tu pojawic."""
    hosty = set(re.findall(r'https?://([^/"\']+)', strona))
    assert hosty <= {'fonts.googleapis.com', 'fonts.gstatic.com'}, \
        f'strona siega poza Google Fonts: {hosty}'


def test_ibm_plex_nie_idzie_z_google_fonts(strona):
    """Kroje tresci sa lokalne — link do Google Fonts dotyczy WYLACZNIE Poppinsa."""
    assert 'family=IBM+Plex' not in strona


def test_strona_nie_laduje_starego_reports_css(strona):
    """reports.css ma wlasny :root z bootstrapowym --primary-color i @import Poppins."""
    assert 'css/reports.css' not in strona


def test_chartjs_idzie_z_lokalnego_vendora_produkcji(strona):
    assert '/production/static/vendor/chart.umd.min.js' in strona


def test_szkielet_oglasza_sie_czytnikom_ekranu(strona):
    assert 'aria-busy="true"' in strona
    assert 'aria-live="polite"' in strona


def test_sa_wszystkie_karty_ukladu_domyslnego_w_kolejnosci_z_makiety(strona):
    znalezione = re.findall(r'data-klucz="([^"]+)"', strona)
    assert znalezione == KLUCZE_KART
    assert len(znalezione) == 10


def test_uklad_domyslny_nie_ma_karty_naleznosci(strona):
    """Partia E, punkt E1: „Należności według" znika TYLKO z układu
    domyślnego. Typ zostaje w katalogu, który modal „+ Dodaj statystykę"
    dostaje w `data-katalog`."""
    assert 'Należności według:' not in strona
    assert not re.findall(r'data-klucz="naleznosci', strona)
    soup = BeautifulSoup(strona, 'html.parser')
    katalog = json.loads(soup.select_one('[data-katalog]')['data-katalog'])
    assert 'naleznosci' in [pozycja['klucz'] for pozycja in katalog]


def test_kazda_karta_ma_cialo_i_stopke(strona):
    for klucz in KLUCZE_KART:
        assert f'data-cialo="{klucz}"' in strona, f'karta {klucz} bez ciala'
    assert strona.count('an-karta__stopka') == len(KLUCZE_KART)


def test_sa_bloki_szkieletu(strona):
    assert strona.count('class="sk') >= 40


def test_naglowki_i_etykiety_kpi_sa_od_razu_prawdziwe(strona_pelna):
    """Spec 6.2: zastepujemy WYLACZNIE wartosci.

    Jednostka siedzi w osobnym elemencie (patrz test nizej), wiec sprawdzamy
    tu sama nazwe miary — „Objetosc" i „Cena", nie „Objetosc m3" i „Cena / m3".
    """
    for etykieta in ('Sprzedaż netto', 'Objętość', 'Zamówienia',
                     'Śr. zamówienie', 'Cena'):
        assert etykieta in strona_pelna
    for tytul in ('Statystyki', 'Należności według:', 'Lejek wycena → zamówienie',
                  'Objętość i cena według:', 'Klienci według:', 'Dostawa według:'):
        assert tytul in strona_pelna


def test_teksty_stopek_sa_dokladnie_z_makiety(strona_pelna):
    """Dwa wyjatki od tytulu testu.

    Karta wojewodztw NIE ma juz stopki z makiety. „Otwórz mapę województw"
    mial sens, dopoki ta karta byla lista poziomych slupkow, a jedyna mapa
    wojewodztw na stronie byla w modalu starej zakladki pod tym linkiem —
    makieta powstala przed kartogramem. Od kartogramu (22.09, patrz
    test_analiza_mapa.py) karta SAMA jest mapa wojewodztw, wiec ten podpis
    pod nia klamalby, ze otwiera ta sama mape drugi raz — link prowadzi do
    INNEJ mapy (metry szescienne z modulu produkcji), wiec dostal tekst
    „Otwórz mapę produkcji".

    Karta naleznosci: makieta (Main.dc.html:328) ma „Wyświetl należności",
    ale Eksplorator nie ma miary „saldo" — wyjscie zawsze pokazywalo netto
    pod etykieta obiecujaca zlotowki naleznosci (przeglad, WAZNE 4). Tekst
    dostal uczciwa etykiete „Wyświetl zamówienia wg statusu", patrz
    test_wyjscie_naleznosci_mowi_prawde_o_tym_co_pokaze nizej."""
    for tekst in ('Wyświetl raport sprzedaży w czasie', 'Wyświetl wszystkie statystyki',
                  'Wyświetl raport kanałów', 'Wyświetl raport handlowców',
                  'Wyświetl miks produktowy', 'Wyświetl raport klientów',
                  'Otwórz mapę produkcji', 'Wyświetl zamówienia wg statusu',
                  'Wyświetl lejek', 'Wyświetl wykończenia', 'Wyświetl raport dostaw'):
        assert tekst in strona_pelna
    assert 'Wyświetl należności' not in strona_pelna


def test_selektory_wymiaru_sa_od_razu_klikalne_i_pelne(strona):
    """Kontrolki maja dzialac przed przyjsciem danych (spec 6.2)."""
    for typ in ('kanal', 'opiekun', 'mix', 'wojewodztwo', 'wykonczenie', 'dostawa'):
        assert f'data-selektor="{KLUCZ[typ]}"' in strona
    for nazwa in wymiary():
        assert f'value="{nazwa}"' in strona, f'brak opcji {nazwa} w selektorze'
    assert POLA['caretaker'].etykieta in strona


def test_pudelko_wykresu_ma_docelowa_wysokosc_juz_w_szkielecie(strona):
    """Canvas ma rysowac sie do gotowego ukladu, nie przestawiac go."""
    assert 'an-wykres--trend' in strona
    assert '--wys-wykres-trend' in open(SCIEZKA_CSS, encoding='utf-8').read()


def test_sa_dwie_kanwy_wykresow(strona):
    """Lejek stracil kanwe, kiedy urosl do pieciu stopni.

    Wykres konwersji miesiecznej zajmowal 118 px w karcie o stalej wysokosci,
    a jego podpis („Konwersja miesiecznie, 2026") siedzial tam, gdzie kazda
    inna karta ma selektor. Piec stopni lejka plus statystyki wycen mieszcza
    sie w tym samym miejscu i odpowiadaja na pytanie, ktore zadal uzytkownik:
    ile wycen, ile zamowionych, ile oplaconych, ile w realizacji.
    """
    # Identyfikator kanwy niesie klucz kafelka (dwa kafelki wykonczenia nie
    # moga dzielic `id`), wiec skladamy go z ukladu domyslnego.
    # Od partii E (punkt E2) karta „Klienci według" ma własne koło — ten sam
    # komponent pierścienia, co karta wykończeń.
    for typ in ('kpi', 'klienci', 'wykonczenie'):
        identyfikator = 'an-wykres-' + KLUCZ[typ].replace(':', '-')
        assert f'id="{identyfikator}"' in strona
    assert strona.count('<canvas') == 3
    assert 'an-wykres-lejek' not in strona


def test_pierscien_ma_miejsce_na_liczbe_w_srodku(strona):
    """Chart.js sam niczego w dziurze pierscienia nie napisze, a to jest
    dominujaca liczba karty (88,8% surowego w makiecie, Main.dc.html:341-342)."""
    assert 'an-pierscien-srodek' in strona
    assert f'data-pole="{KLUCZ["wykonczenie"]}.udzial"' in strona
    assert f'data-pole="{KLUCZ["wykonczenie"]}.nazwa"' in strona


def test_ostrzezenie_salda_jest_podsekcja_wiec_wiersze_ida_nad_nie(strona_pelna):
    """rysujWiersze (Zadanie 7) wstawia wiersze PRZED pierwsza .an-podsekcja.
    Bez tej klasy piec kubelkow wieku wyladowaloby POD czerwonym ostrzezeniem,
    odwrotnie niz w makiecie — i zaden test tego nie zlapie po fakcie, bo
    kolejnosci DOM po wypelnieniu nikt nie sprawdza."""
    cialo = strona_pelna.split(f'data-cialo="{KLUCZ["naleznosci"]}"')[1].split('an-karta__stopka')[0]
    assert 'an-podsekcja' in cialo
    pozycja_podsekcji = cialo.index('an-podsekcja')
    pozycja_ostatniego_wiersza = cialo.rindex('an-wiersz')
    assert pozycja_ostatniego_wiersza < pozycja_podsekcji, \
        'ostrzezenie musi byc OSTATNIM elementem ciala karty naleznosci'


def test_przycisk_pobierz_zamowienia_zniknal_bo_prowadzil_do_tylko_do_odczytu(strona):
    """Regresja z przegladu (WAZNE 5): przycisk „Pobierz zamówienia" linkowal
    do reports.reports_home (href="/reports/") — starej tabeli, ktora commit
    8d5f1e2 przelaczyl w tryb tylko do odczytu (routers.py:
    tylko_odczyt_starej_zakladki odbija KAZDY POST 409-ka „Ta tabela jest
    już tylko do odczytu"). Klikniecie obiecywalo pobranie zamowien i konczylo
    sie scianka. Naprawa: przycisk usuniety (uzasadnienie w komentarzu w
    dashboard.html) — prawdziwe pobieranie zyje w Arkuszu, ktorego przycisk
    zostaje na miejscu."""
    assert 'Pobierz zamówienia' not in strona
    assert 'href="/reports/arkusz"' in strona
    # 'Otwórz mapę produkcji' legalnie zostaje na reports_home (to odczyt
    # map-statistics, nie akcja zapisu) — usuniecie jednego przycisku nie
    # moze zabrac tej trasy calkiem ze strony.
    assert 'href="/reports/?mapa=1"' in strona


def test_wyjscie_naleznosci_mowi_prawde_o_tym_co_pokaze(strona_pelna):
    """Regresja z przegladu (WAZNE 4): etykieta „Wyświetl należności" obiecywala
    naleznosci, a wyjscie prowadzilo do Eksploratora z miara=netto — Eksplorator
    w ogole nie ma miary „saldo" (MIARY_PANELU/MIARY_PRZESTAWIENIA), wiec
    klikniecie zawsze pokazywalo NETTO pogrupowane wedlug statusu zamowienia,
    nie zlotowki naleznosci. Etykieta ma teraz mowic, co naprawde pokaze."""
    assert 'Wyświetl należności' not in strona_pelna
    fragment = strona_pelna.split(f'data-cialo="{KLUCZ["naleznosci"]}"')[1]
    assert 'Wyświetl zamówienia wg statusu' in fragment
    # Wyjscie samo w sobie zostaje bez zmian (netto x current_status) — to
    # jest juz jedyna dzialajaca kombinacja, ktora Eksplorator umie pokazac.
    assert 'wymiar=current_status' in fragment
    assert 'miara=netto' in fragment


def test_okres_domyslny_to_biezacy_miesiac(client):
    # `dzis_lokalnie()`, nie `date.today()`: kontener chodzi na UTC, a strona
    # liczy okres w czasie polskim. Pierwszego dnia miesiąca między 00:00
    # a 02:00 `date.today()` jest jeszcze w poprzednim miesiącu (kontrola
    # końcowa, DROBNE 4).
    from modules.reports.analiza_service import dzis_lokalnie
    strona = client.get('/reports/analiza').get_data(as_text=True)
    assert dzis_lokalnie().replace(day=1).isoformat() in strona


def test_zly_okres_w_adresie_nie_wywala_strony_tylko_wraca_do_domyslnego(client):
    """Nieaktualna zakladka w przegladarce ma pokazac dashboard, nie blad."""
    odpowiedz = client.get('/reports/analiza?od=wczoraj&do=kiedys')
    assert odpowiedz.status_code == 200


def test_zly_wymiar_w_adresie_tez_nie_wywala_strony(client):
    assert client.get('/reports/analiza?kanal=payment_date').status_code == 200


def test_stary_parametr_wymiaru_w_adresie_nie_zmienia_wymiaru_kafelka(client):
    """Od Planu D wymiar kafelka jest czescia ZAPISANEGO ukladu, nie adresu
    (`?kanal=` przy trzech kafelkach kanalow nie mialby jak byc jednoznaczny).
    Stary adres z zakladki ma dac pulpit, a kafelek kanalow — SWOJ wymiar.

    Dawna wersja tego testu szukala `value="caretaker" selected` w CALEJ
    stronie i przechodzila z niewlasciwego powodu: trafiala w selektor karty
    opiekunow, ktora caretaker ma domyslnie. Asercja celuje wiec w selektor
    KONKRETNEGO kafelka, po jego kluczu instancji."""
    odpowiedz = client.get('/reports/analiza?kanal=caretaker')
    assert odpowiedz.status_code == 200
    soup = BeautifulSoup(odpowiedz.get_data(as_text=True), 'html.parser')
    kafelek = soup.select_one(f'[data-kafelek][data-klucz="{KLUCZ["kanal"]}"]')
    assert kafelek is not None
    wybor = kafelek.select_one(f'select[data-selektor="{KLUCZ["kanal"]}"]')
    assert wybor is not None
    assert wybor.select_one('option[selected]').get('value') == 'order_source'
    assert kafelek.get('data-wymiar') == 'order_source'


def test_opis_okresu_ma_forme_z_makiety():
    from datetime import date
    from modules.reports.analiza_service import nazwa_zakresu, opis_okresu

    assert opis_okresu(date(2026, 9, 1), date(2026, 9, 21)) == '1–21 wrz 2026'
    assert opis_okresu(date(2026, 1, 1), date(2026, 9, 21)) == '1 sty – 21 wrz 2026'
    assert opis_okresu(date(2025, 12, 1), date(2026, 1, 5)) == '1 gru 2025 – 5 sty 2026'
    assert nazwa_zakresu(date(2026, 3, 1), date(2026, 3, 31)) == 'pełny miesiąc'


def test_pasek_pokazuje_nazwe_i_opis_okresu(strona):
    # Dzień w czasie polskim, tak jak liczy go strona — patrz
    # `test_okres_domyslny_to_biezacy_miesiac`. Z `date.today()` test oblewał
    # co noc między 00:00 a 02:00 („zakres własny" zamiast „bieżący miesiąc").
    from modules.reports.analiza_service import dzis_lokalnie, nazwa_zakresu, opis_okresu

    dzis = dzis_lokalnie()
    assert nazwa_zakresu(dzis.replace(day=1), dzis) in strona
    assert opis_okresu(dzis.replace(day=1), dzis) in strona


def test_animacja_szkieletu_respektuje_prefers_reduced_motion():
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    assert 'prefers-reduced-motion' in css


# --- tytul: JEDNO podkreslenie ----------------------------------------------
# .an-tytul niesie wlasne border-bottom na szerokosc tekstu (makieta
# Main.dc.html:93). Globalna .title-with-underline ze static/css/style.css
# dokłada DRUGIE — pasek 70x4 px przez ::after, 8 px nizej. Obie naraz daja
# dwa podkreslenia pod jednym tytulem. Spec 6.6 wymienia „page-title
# title-with-underline" jako konwencje repo, wiec bez tego testu klasy wracaly
# przy pierwszym sprzataniu jako rzekomo brakujace.

def test_tytul_ma_jedno_podkreslenie_a_nie_dwa(client):
    tresc = client.get('/reports/analiza').get_data(as_text=True)
    assert 'an-tytul">' in tresc, 'tytul stracil wlasna klase'
    assert 'title-with-underline' not in tresc, \
        'globalna klasa dokłada drugie podkreslenie przez ::after'
    assert 'page-title' not in tresc, \
        'page-title nie jest na tej stronie zdefiniowana — tylko myli'


def test_arkusz_nie_dostaje_globalnych_klas_tytulu_z_podwojnym_podkresleniem(client):
    """Zadanie 7 zastapilo zaslepke prawdziwym arkuszem: pelne okno, pasek
    narzedzi zamiast naglowka strony (patrz docstring arkusz.html) — strona
    CELOWO nie ma wlasnego elementu .an-tytul, wiec nie mozna tu powtorzyc
    testu z /reports/analiza wprost. Zasada „jedno podkreslenie, nie dwa"
    i tak obowiazuje: pilnujemy, zeby globalne klasy ze static/css/style.css
    (ktorych ten szablon nie laduje) nie wkradly sie tu przy kolejnej
    zmianie."""
    tresc = client.get('/reports/arkusz').get_data(as_text=True)
    assert 'title-with-underline' not in tresc, \
        'globalna klasa dokłada drugie podkreslenie przez ::after'
    assert 'page-title' not in tresc, \
        'page-title nie jest na tej stronie zdefiniowana — tylko myli'


def test_podkreslenie_tytulu_jest_w_analiza_css():
    """Skoro zdejmujemy globalna klase, wlasna musi naprawde rysowac kreske."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    blok = css.split('.an-tytul {', 1)[1].split('}', 1)[0]
    assert 'border-bottom' in blok and 'accent' in blok


# --- zaslepka arkusza (Plan C) ----------------------------------------------

def test_przycisk_arkusz_prowadzi_do_istniejacej_trasy(strona, app):
    assert 'href="/reports/arkusz"' in strona
    assert '/reports/arkusz' in [r.rule for r in app.url_map.iter_rules()]


# USUNIETO test_zaslepka_arkusza_mowi_wprost_ze_arkusz_jeszcze_nie_istnieje:
# asercjonowal tresc TYMCZASOWEJ zaslepki („w przygotowaniu" + link powrotny)
# sprzed Zadania 7. Zadanie 7 zastapilo zaslepke prawdziwym arkuszem —
# /reports/arkusz dziala i nie zawiera juz tego tekstu, wiec test byl
# merytorycznie martwy (asercjonowal stan, ktory swiadomie przestal byc
# prawda, a nie regresje). Zaslepke jako etap posredni pilnowal tylko na
# czas Zadan 1-6; dzialajacy arkusz maja pokrywac testy w sekcjach ponizej
# (siatka/JS wlasnego pasma) oraz test_przycisk_arkusz_prowadzi_do_istniejacej_trasy
# powyzej.


# --- analiza.js: kontrakt z payloadem i higiena kodu ------------------------

SCIEZKA_JS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'analiza.js')


@pytest.fixture()
def js():
    return open(SCIEZKA_JS, encoding='utf-8').read()


def test_js_nie_siega_do_zadnego_cdn(js):
    for zakazane in ('cdn.jsdelivr.net', 'cdnjs.cloudflare.com', 'unpkg.com',
                     'fonts.googleapis.com'):
        assert zakazane not in js


def test_js_nie_wstawia_danych_przez_innerhtml(js):
    """Slowniki z BaseLinkera sa brudne — delivery_method miewa wpisy w rodzaju
    '680 zl za nasz transport jesli chce'. Wartosci wchodza przez textContent."""
    assert '.innerHTML =' not in js
    assert 'insertAdjacentHTML' not in js


def test_js_uzywa_chartjs_tylko_w_dwoch_miejscach(js):
    """Slupki w kartach sa div-ami, tak jak w makiecie. Chart.js obsluguje
    wylacznie trend i pierscien wykonczenia — lejek rysuje sie wierszami
    ze slupkami, jak kazda inna karta (patrz test kanw wyzej)."""
    assert js.count('new Chart(') == 2


def test_js_zdejmuje_aria_busy_po_wypelnieniu(js):
    assert "aria-busy" in js
    assert "an-gotowe" in js


def test_js_pokazuje_blad_po_polsku(js):
    assert 'an-blad' in js
    assert 'Nie udało się' in js


def test_js_formatuje_liczby_po_polsku(js):
    assert "Intl.NumberFormat('pl-PL'" in js


def test_kazde_data_pole_z_szablonu_istnieje_w_payloadzie(client, app, strona):
    """Kontrakt szablon <-> API. Zmiana nazwy klucza w serwisie bez zmiany
    szablonu zostawilaby cicha dziure zamiast liczby.

    Od Planu D pole kafelka wymiarowego zaczyna sie KLUCZEM INSTANCJI
    (`klienci:liczba_zamowien.uwaga`) i czyta sie z `dane.karty[klucz]`,
    a pole kafelka bez wymiaru (`kpi.netto`, `lejek.uwaga`) — z bloku
    najwyzszego poziomu, jak dawniej. Wzorzec lapie oba ksztalty: dawny
    `[a-z_.]+` po cichu przepuszczal kazde pole z dwukropkiem."""
    with app.app_context():
        _zamowienie_widok(app)

    dane = client.get('/reports/api/analytics').get_json()
    sciezki = set(re.findall(r'data-pole="([a-z_.:]+)"', strona))
    assert any(':' in s for s in sciezki), 'wzorzec nie widzi pol kafelkow wymiarowych'
    # Pola wyliczane po stronie JS z innych kluczy payloadu — nie sa sciezkami.
    pochodne = {'trend.rok_biezacy', 'trend.rok_poprzedni',
                # Druga liczba KPI (Zadanie 10): JS czyta ja z
                # dane.porownanie.kpi[pole], nie z tej doslownej sciezki —
                # data-pole tu jest tylko "hakiem" do znalezienia wezla w DOM.
                'kpi.netto.porownanie', 'kpi.objetosc.porownanie',
                'kpi.zamowienia.porownanie', 'kpi.srednie_zamowienie.porownanie',
                'kpi.cena_za_m3.porownanie',
                # Wariant „szt." pola Sprzedaż (przełącznik miary, 24.09.2026)
                # — ta sama rola haka, co wyżej: dane.porownanie.kpi.sztuki.
                'kpi.sztuki.porownanie'}
    # Dla kafelkow wymiarowych o tym, czy pole jest pochodne, decyduje OGON
    # sciezki (to, co stoi po kluczu instancji).
    pochodne_kafelka = {'roznica', 'udzial', 'nazwa', 'nowi', 'koszt_kuriera'}

    for sciezka in sciezki - pochodne:
        czesci = sciezka.split('.')
        if ':' in czesci[0]:
            if czesci[-1] in pochodne_kafelka:
                continue
            assert czesci[0] in dane['karty'], f'szablon pyta o kafelek {czesci[0]}'
            wezel, czesci = dane['karty'][czesci[0]], czesci[1:]
        else:
            wezel = dane
        for czesc in czesci:
            assert isinstance(wezel, dict) and czesc in wezel, \
                f'szablon pyta o {sciezka}, a payload nie ma {czesc}'
            wezel = wezel[czesc]


def _zamowienie_widok(app):
    """Jedno zamowienie, zeby payload nie byl caly pusty.

    Data w czasie polskim: domyslny okres strony to biezacy miesiac liczony
    przez `dzis_lokalnie()`, a `date.today()` w kontenerze (UTC) pierwszego
    dnia miesiaca przed 02:00 wypadaloby w poprzednim miesiacu."""
    from decimal import Decimal
    from modules.reports.analiza_service import dzis_lokalnie
    zam = SalesOrder(baselinker_order_id=1, date_created=dzis_lokalnie(),
                     balance_due=Decimal('0'), order_source='shop',
                     caretaker='Ewa Fikcyjna', current_status='Nowe',
                     delivery_method='Kurier', delivery_cost=Decimal('100.00'))
    db.session.add(zam)
    db.session.flush()
    db.session.add(SalesOrderItem(order_id=zam.id, value_net=Decimal('1000.00'),
                                  total_volume=Decimal('0.5'), group_type='towar',
                                  wood_species='dab', finish_state='surowy', quantity=1))
    db.session.commit()


def test_szablon_laduje_analiza_js(strona):
    assert 'js/analiza.js' in strona


def test_js_nie_przepisuje_adresu_doslownie_do_api(js):
    """Trasa HTML cofa zly parametr do domyslnego, ale adresu nie zmienia.
    Przepisany doslownie do /api/analytics dostalby 400 i uzytkownik zobaczylby
    poprawny dashboard plus czerwony pasek sekunde pozniej."""
    assert 'window.location.search' not in js.split('function adresDanych')[1][:400]
    assert 'parametryStanu' in js
    assert "korzen.getAttribute('data-od')" in js


def test_js_normalizuje_adres_przy_wejsciu(js):
    """Po wejsciu z nieaktualnej zakladki adres w pasku ma przestac klamac.
    replaceState, nie pushState — to nie jest nowy stan widoku."""
    assert 'history.replaceState' in js


def test_lewa_czesc_paska_nie_jest_wezsza_niz_najszersza_grupa_wykluczen(js):
    """Porządki końcowe, punkt 3d (weryfikacja E8, D4). Przy podstawie
    320 px lewa część paska bywała węższa niż grupa „Wykończenie" (ok. 350 px)
    i „olejowany" schodził sam pod podpis grupy (ok. 930–950 i 1024–1040 px).
    Podstawa to teraz co najmniej szerokość najszerszej grupy, mierzona przez
    analiza.js — przy braku miejsca do kolejnej linii schodzi prawa część,
    a grupa zostaje w całości. Sprawdzone skanem szerokości w przeglądarce;
    tu pilnujemy, żeby żadne z trzech ogniw nie zniknęło."""
    import re
    css = open(os.path.join(KORZEN, 'modules', 'reports', 'static', 'css', 'analiza.css'),
               encoding='utf-8').read()
    regula = css.split('.an-pasek__lewy {')[1].split('}')[0]
    assert re.search(r'flex:\s*1 1 max\(320px, var\(--an-najszersza-grupa, 0px\)\)', regula)
    assert 'min-width: 0' in regula

    bez_komentarzy = re.sub(r'(?m)^\s*//.*$', '', js)
    pomiar = bez_komentarzy.split('function ustawPodstaweWykluczen(')[1].split('\n  }\n')[0]
    assert "setProperty('--an-najszersza-grupa'" in pomiar
    # Grupa mierzona bez ściśnięcia (klasa pomiaru z arkusza), klasa zdjęta
    # zaraz po pomiarze.
    assert "classList.add('an-wyk-grupa--pomiar')" in pomiar
    assert "classList.remove('an-wyk-grupa--pomiar')" in pomiar
    assert re.search(r'\.an-wyk-grupa--pomiar \{ flex: none; \}', css)
    start = bez_komentarzy.split("document.addEventListener('DOMContentLoaded'")[1]
    assert 'ustawPodstaweWykluczen();' in start
    assert 'document.fonts.ready.then(ustawPodstaweWykluczen)' in start


def test_js_kropka_pigulki_wykluczen_zostaje_biala(js):
    """Porządki końcowe, punkt 3c (weryfikacja E8, D2). Arkusz robi kropkę
    pigułki „Bez: …" białą (`.an-chip--wykluczenia .an-chip__kropka`), ale
    `rysujSegmenty` nadpisywało ją stylem inline koloru segmentu — po
    wczytaniu danych kropka była pomarańczowa na ciemnopomarańczowym tle."""
    import re
    css = open(os.path.join(KORZEN, 'modules', 'reports', 'static', 'css', 'analiza.css'),
               encoding='utf-8').read()
    assert re.search(r'\.an-chip--wykluczenia \.an-chip__kropka \{ background: #FFF; \}', css)
    cialo = js.split('function rysujSegmenty(')[1].split('\n  }\n')[0]
    przypisania = [linia.strip() for linia in cialo.splitlines()
                   if 'kropka.style.background' in linia]
    assert przypisania == [
        'if (!(i === 0 && segment.wykluczenia)) { kropka.style.background = segment.kolor; }']


def test_js_bierze_najlepszego_i_roznice_gotowe_z_payloadu(js):
    """Spec 6.1: zadna liczba nie jest liczona w dwoch miejscach."""
    # Od Planu D kafelek czyta SWOJA karte (`dane.karty[klucz]`), a nie
    # zaszyty klucz typu — stad `karta.`, nie `dane.karty.opiekun.`.
    assert 'karta.najlepszy' in js
    assert 'karta.roznica_do_surowego' in js
    # Slad po liczeniu w przegladarce: dzielenie netto przez zamowienia.
    assert 'w.netto / w.zamowienia' not in js


def test_js_kolory_kawalkow_w_stalej_kolejnosci_a_ogon_w_kolorze_pozostalych(js):
    """Weryfikacja partii E (D5): rozwinięty ogon „Pozostałe (14)" dostawał
    kolory po indeksie modulo długość palety — Podlaskie było pomarańczowe jak
    Śląskie, Kujawsko-Pomorskie fioletowe jak kawałek „Pozostałe". Kolory
    kategorii NIGDY nie idą cyklicznie; wiersze ogona to części jednego
    kawałka, więc mają jego kolor. Jedna funkcja koloru dla pierścienia
    i obu legend (wykończenia, koło klientów).

    Porządki końcowe, punkt 3b: indeks koloru przychodzi Z SERWERA
    (`indeks_koloru`, za wartością, nie za miejscem w rankingu — semantykę
    sprawdza test_analiza_wykluczenia.py). Pozycja wiersza w pętli nie może
    już decydować o kolorze ani w pierścieniu, ani w legendach; wiersz ogona
    dostaje od serwera indeks kawałka „Pozostałe"."""
    import re
    bez_komentarzy = re.sub(r'(?m)^\s*//.*$', '', re.sub(r'/\*.*?\*/', '', js, flags=re.S))
    assert '% KOLORY_PIERSCIENIA' not in bez_komentarzy
    kolor = bez_komentarzy.split('function kolorKawalka(')[1].split('\n  }')[0]
    assert 'Math.min(' in kolor

    def cialo(nazwa):
        return bez_komentarzy.split('function ' + nazwa + '(')[1].split('\n  }\n')[0]

    assert 'kolorKawalka(w.indeks_koloru)' in cialo('rysujPierscien')
    assert 'kolorKawalka(i)' not in cialo('rysujPierscien')
    for legenda in ('rysujLegendeWykonczenia', 'rysujLegendeKola'):
        tresc = cialo(legenda)
        # Każde wywołanie koloru bierze indeks z wiersza payloadu.
        wywolania = re.findall(r'kolorKawalka\(([^)]*)\)', tresc)
        assert wywolania == ['w.indeks_koloru'], (legenda, wywolania)
        # Wiersz ogona nie dostaje kolejnych indeksów pętli.
        assert 'i + 1 + j' not in tresc, legenda


def test_js_paleta_kola_zgadza_sie_z_serwerem_a_neutralny_to_szary(js):
    """Decyzja z 24.09.2026: kolor kawałka idzie za encją, a „Pozostałe"
    i każda wartość spoza czołówki karty bez wykluczeń mają JEDEN kolor
    neutralny. Serwer podaje tylko indeks (`analiza_service.INDEKS_NEUTRALNY`,
    `KOLORY_KOLA`), więc paleta w przeglądarce musi mieć tyle samo kolorów,
    a pod indeksem neutralnym — szary `--neutral` z arkusza stylów. Kilka
    neutralnych kawałków obok siebie rozdziela odstęp 2 px, inaczej zlałyby
    się w jeden: obrys w kolorze tła karty, a nie `spacing` z Chart.js, którego
    przerwa rośnie z kątem kawałka i między małymi kawałkami prawie znika."""
    from modules.reports.analiza_service import INDEKS_NEUTRALNY, KOLORY_KOLA
    paleta = re.findall(r"'(#[0-9A-Fa-f]{6})'",
                        js.split('var KOLORY_PIERSCIENIA = [')[1].split('];')[0])
    assert len(paleta) == KOLORY_KOLA
    assert len({kolor.upper() for kolor in paleta}) == len(paleta)
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    neutralny = re.search(r'--neutral:\s*(#[0-9A-Fa-f]{6})', css).group(1)
    assert paleta[INDEKS_NEUTRALNY].upper() == neutralny.upper()
    cialo = js.split('function rysujPierscien(')[1].split('\n  }\n')[0]
    assert "getPropertyValue('--surface')" in cialo and 'borderColor: tloKarty' in cialo
    assert 'spacing:' not in cialo


def test_js_maly_kawalek_kola_dostaje_obrys_zero_a_najazd_nie_szarzy_szwu(js):
    """Kontrola koloru (24.09.2026), znalezisko WAZNE 1: obrys 2 px jest
    wysrodkowany na granicy kawalka, wiec zabiera po 1 px z kazdej strony.
    Na promieniu wewnetrznym pierscienia (kadr 104x104 px, cutout 62% —
    promien ok. 32 px) dlugosc luku kawalka o udziale ponizej ok. 1% jest juz
    krotsza niz sama szerokosc obrysu, wiec obrys go czesciowo albo (przy
    jeszcze mniejszym udziale) calkiem zjada — legenda dalej pokazuje jego
    kolor, ktorego na kole nie widac. Kawalek ponizej progu ma wiec dostawac
    borderWidth 0, a udzial ma pochodzic z payloadu (w.udzial), nie z liczenia
    w przegladarce.

    Znalezisko DROBNE: Chart.js domyslnie szarzy obrys przy najezdzie
    (getHoverColor z bieli robi #E6E6E6), wiec szew miedzy dwoma kawalkami
    traci kolor tla karty. hoverBorderColor ma wiec byc tym samym kolorem
    co borderColor."""
    cialo = js.split('function rysujPierscien(')[1].split('\n  }\n')[0]
    # Prog jest zadeklarowany raz, poza funkcja (nie liczony przy kazdym
    # rysowaniu), ale uzywany w niej — szukamy go w calym pliku.
    prog = re.search(r'var PROG_WIDOCZNOSCI_OBRYSU\s*=\s*([\d.]+)', js)
    assert prog, 'brak stalej progu widocznosci obrysu'
    wartosc_progu = float(prog.group(1))
    assert 0 < wartosc_progu < 5, 'prog ma sensownie odcinac tylko bardzo male kawalki'

    # borderWidth liczy sie PER KAWALEK (tablica, nie jedna liczba dla calego
    # kola) i bierze udzial z payloadu — zero liczb biznesowych w JS.
    assert re.search(
        r"borderWidth:\s*wiersze\.map\(function \(w\) \{\s*"
        r"return kawalkow > 1 && w\.udzial >= PROG_WIDOCZNOSCI_OBRYSU \? 2 : 0;",
        cialo)
    assert 'hoverBorderColor: tloKarty' in cialo


def test_js_wypelnia_srodek_pierscienia(js):
    # Od partii E8 (punkt 4b) środek obu kół wypełnia jedna funkcja.
    fragment = js.split('function rysujDodatkiWykonczenia')[1].split('\n  }')[0]
    assert 'rysujSrodekPierscienia(kafelek, karta.najwiekszy)' in fragment
    srodek = js.split('function rysujSrodekPierscienia')[1].split('\n  }')[0]
    assert "klucz + '.udzial'" in srodek
    assert "klucz + '.nazwa'" in srodek


# --- sterowanie: selektory wymiaru i zakres dat ------------------------------

def test_menu_zakresu_ma_presety_i_pola_dat(strona):
    assert 'id="an-zakres-menu"' in strona
    for preset in ('biezacy-miesiac', 'poprzedni-miesiac', 'biezacy-kwartal',
                   'biezacy-rok', 'calosc'):
        assert f'data-preset="{preset}"' in strona
    assert 'id="an-zakres-od"' in strona
    assert 'id="an-zakres-do"' in strona


def test_presety_maja_polskie_etykiety(strona):
    for etykieta in ('bieżący miesiąc', 'poprzedni miesiąc', 'bieżący kwartał',
                     'bieżący rok', 'całość'):
        assert etykieta in strona


def test_js_reaguje_na_zmiane_selektora_wymiaru(js):
    assert "data-selektor" in js
    assert "addEventListener('change'" in js


def test_js_zapisuje_stan_w_adresie(js):
    """Widok ma dac sie zapisac w zakladkach — spec 6.3."""
    assert 'history.replaceState' in js or 'history.pushState' in js
    assert 'URLSearchParams' in js


def test_js_pokazuje_szkielet_przy_kazdym_przeladowaniu(js):
    """Ten sam mechanizm co przy wejsciu (spec 6.2)."""
    assert 'pokazSzkielet' in js
    assert js.count('pokazSzkielet()') >= 1


def test_js_podmienia_opis_okresu_z_payloadu(js):
    assert "okres.nazwa" in js
    assert "okres.opis" in js


def test_js_nie_liczy_dat_presetow_recznie_poza_lista(js):
    """Presety maja byc jawna lista, a nie rozsypanymi warunkami w handlerze."""
    assert 'PRESETY' in js


def test_js_waliduje_parametry_po_cofnieciu_w_przegladarce(js):
    """Po cofnieciu adres jest zrodlem, ale nie wolno mu ufac — zla data
    poleciałaby do /api/analytics i wrocilaby jako 400. Wymiarow kart od
    Planu D w adresie nie ma, wiec nie ma czego walidowac po opcjach
    selektora; zostaje format daty."""
    assert 'odczytajStanZAdresu' in js
    fragment = js.split('function odczytajStanZAdresu')[1].split('\n  }')[0]
    assert r'/^\d{4}-\d{2}-\d{2}$/' in fragment
    assert 'stan.wymiary' not in fragment


# --- komponent wyboru filtra ------------------------------------------------

SCIEZKA_JS_FILTRA = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'filtr.js')


@pytest.fixture()
def js_filtra():
    return open(SCIEZKA_JS_FILTRA, encoding='utf-8').read()


def test_komponent_filtra_jest_jeden_i_globalny(js_filtra):
    """Dashboard i Eksplorator maja uzywac TEGO SAMEGO popovera."""
    assert 'window.FiltrWymiaru' in js_filtra
    assert 'otworz' in js_filtra


def test_komponent_filtra_nie_wstawia_danych_przez_innerhtml(js_filtra):
    """Wartosci wymiarow to wolny tekst z BaseLinkera."""
    assert '.innerHTML =' not in js_filtra
    assert 'insertAdjacentHTML' not in js_filtra


def test_komponent_filtra_pobiera_wartosci_z_endpointu(js_filtra):
    assert 'wartosci-wymiaru' in js_filtra or 'urlWartosci' in js_filtra
    assert 'fetch(' in js_filtra


def test_komponent_filtra_odrzuca_spozniona_liste_wartosci(js_filtra):
    """Porządki końcowe, punkt 3g. Szybka zmiana wymiaru w popoverze daje
    kilka żądań w locie; spóźniona lista starego wymiaru zastępowała nowszą
    (i zapamiętywała jej zaznaczenia pod złym wymiarem). Ten sam wzorzec
    numeru żądania co `numerLadowania` w analiza.js: numer podbijany przy
    każdym żądaniu i sprawdzany w KAŻDYM kroku odpowiedzi, także w błędzie."""
    cialo = js_filtra.split('function wczytajWartosci(')[1].split('\n    }\n')[0]
    assert 'numerWartosci += 1;' in cialo
    assert 'var numer = numerWartosci;' in cialo
    # Pierwsze sprawdzenie przed czyszczeniem listy w odpowiedzi i w błędzie.
    po_fetch = cialo.split('fetch(')[1]
    assert po_fetch.count('numer !== numerWartosci') == 3
    for krok in ('.then(function (odp)', '.then(function (dane)', '.catch(function (blad)'):
        # Sprawdzenie stoi w TYM kroku, przed zamknięciem jego funkcji.
        fragment = po_fetch.split(krok)[1]
        koniec_kroku = fragment.index('\n        })')
        assert fragment.index('numer !== numerWartosci') < koniec_kroku, krok


def test_komponent_filtra_zamyka_sie_escapem_i_oddaje_fokus(js_filtra):
    assert "'Escape'" in js_filtra
    assert '.focus()' in js_filtra


def test_komponent_filtra_ma_trzy_przyciski_po_polsku(js_filtra):
    for etykieta in ('Zastosuj', 'Wyczyść', 'Anuluj'):
        assert etykieta in js_filtra


def test_komponent_filtra_buduje_tekst_w_formacie_z_zadania_2(js_filtra):
    """Ten sam format co parsuj_filtr: pole:wartosc|wartosc,pole:wartosc,
    z wartosciami zakodowanymi encodeURIComponent."""
    assert 'encodeURIComponent' in js_filtra
    assert "':'" in js_filtra
    assert "'|'" in js_filtra
    assert "','" in js_filtra


def test_css_ma_style_popovera_filtra():
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    assert '.an-filtr-popover' in css
    assert '.an-filtr-wartosc' in css


# --- pasek segmentow --------------------------------------------------------

def test_chip_dodaj_porownanie_jest_klikalny(strona):
    """W Zadaniu 6 byl wylaczony, bo nie mial czego robic. Teraz ma."""
    fragment = strona.split('an-chip--dodaj')[1].split('>')[0]
    assert 'disabled' not in fragment
    assert 'id="an-dodaj-porownanie"' in strona


def test_pasek_segmentow_ma_miejsce_na_drugi_chip(strona):
    assert 'id="an-segmenty"' in strona
    assert 'Wszystkie zamówienia' in strona


def test_karty_bez_segmentu_maja_adnotacje_w_szablonie(strona_pelna):
    for typ in ('wnioski', 'klienci', 'naleznosci', 'lejek'):
        assert f'data-bez-segmentu="{KLUCZ[typ]}"' in strona_pelna
    assert 'segment nie dotyczy tej karty' in strona_pelna


def test_js_otwiera_popover_filtra_z_chipa(js):
    assert 'FiltrWymiaru.otworz' in js
    assert 'an-dodaj-porownanie' in js


def test_js_trzyma_segment_w_adresie_pod_wlasna_nazwa(js):
    """`porownanie`, nie `filtr` — w Eksploratorze `filtr` znaczy co innego."""
    assert "'porownanie'" in js


def test_js_rysuje_druga_serie_z_payloadu_a_nie_liczy_jej(js):
    assert 'dane.porownanie' in js
    assert 'porownanie.karty' in js


def test_js_zdejmuje_nakladke_roku_poprzedniego_przy_segmencie(js):
    """Trzy zestawy slupkow w pudelku 152 px sa nieczytelne — przy wlaczonym
    segmencie nakladka roku poprzedniego ustepuje serii porownawczej."""
    assert 'dane.porownanie ?' in js or 'if (dane.porownanie)' in js


def test_css_ma_style_drugiego_chipa_i_drugiego_slupka():
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    assert '.an-chip--porownanie' in css
    assert '.an-wiersz__wypelnienie--porownanie' in css
    assert '.an-bez-segmentu' in css


# --- wyjscia z kart przez url_for (Zadanie 12) ------------------------------

def test_wyjscia_z_kart_ida_przez_url_for_a_nie_doslownym_adresem():
    """Zadanie 6 zostawilo w szablonie doslowne '/reports/eksplorator?...',
    bo trasa jeszcze nie istniala. Po Zadaniu 12 nie moze go tam byc — sprawdzamy
    ZRODLO szablonu, bo w wyrenderowanym HTML-u oba warianty wygladaja tak samo."""
    # Od Planu D karty mieszkaja w makrach _kafelki.html, a dashboard.html
    # wlacza je petla z _siatka.html — sprawdzamy wszystkie trzy pliki.
    katalog = os.path.join(KORZEN, 'modules', 'reports', 'templates', 'analiza')
    for nazwa in ('dashboard.html', '_siatka.html', '_kafelki.html'):
        zrodlo = open(os.path.join(katalog, nazwa), encoding='utf-8').read()
        assert "'/reports/eksplorator" not in zrodlo, nazwa
    kafelki = open(os.path.join(katalog, '_kafelki.html'), encoding='utf-8').read()
    assert kafelki.count("url_for('reports.eksplorator'") == 10  # 11 kart minus mapa


def test_wszystkie_wyjscia_z_kart_prowadza_pod_dzialajacy_adres(strona, client):
    """Jinja escapuje & w atrybucie do &amp;, wiec bez html.unescape Werkzeug
    potraktowalby `amp;przestawienie` jako osobny parametr, trasa cofnelaby sie
    do domyslnych i zwrocila 200 — test przeszedlby, nie sprawdziwszy niczego."""
    import html

    adresy = set(re.findall(r'href="(/reports/eksplorator[^"]*)"', strona))
    assert len(adresy) >= 1
    for zakodowany in adresy:
        adres = html.unescape(zakodowany)
        assert '&amp;' not in adres
        odpowiedz = client.get(adres)
        assert odpowiedz.status_code == 200, f'martwe wyjscie: {adres}'
        # I ze parametr faktycznie doszedl: wymiar z adresu ma byc zaznaczony.
        wymiar = re.search(r'[?&]wymiar=([a-z_]+)', adres).group(1)
        tresc = odpowiedz.get_data(as_text=True)
        assert re.search(rf'value="{wymiar}"\s+selected', tresc), \
            f'Eksplorator zignorowal wymiar z adresu: {adres}'


# --- wyjscia z kart: adres ma nadazac za stanem dashboardu ------------------

def test_kazde_wyjscie_do_eksploratora_niesie_dane_do_przepisania(strona_pelna):
    """Stopki maja adres wyrenderowany serwerowo, a zmiana okresu i wymiaru
    karty leci przez fetch + pushState — bez tych atrybutow analiza.js nie ma
    z czego zlozyc aktualnego adresu i kazde wyjscie po pierwszej interakcji
    prowadzi do Eksploratora z nieaktualnym okresem."""
    assert strona_pelna.count('data-wyjscie-miara=') == 10
    # Od Planu D KAZDE wyjscie niesie wprost wymiar swojego kafelka — klucz
    # karty (`data-wyjscie-karta`) nie mowi, KTORY z trzech kafelkow kanalow.
    assert 'data-wyjscie-karta' not in strona_pelna
    soup = BeautifulSoup(strona_pelna, 'html.parser')
    for wyjscie in soup.select('a[data-wyjscie-miara]'):
        assert wyjscie.get('data-wyjscie-wymiar'), wyjscie
    for instancja in UKLAD_DOMYSLNY:
        if instancja.typ in ('kanal', 'opiekun', 'mix', 'wykonczenie', 'dostawa'):
            kafelek = soup.select_one(f'[data-klucz="{instancja.klucz}"]')
            wyjscie = kafelek.select_one('a[data-wyjscie-miara]')
            assert wyjscie.get('data-wyjscie-wymiar') == instancja.wymiar
    for wymiar in ('client_origin', 'current_status'):
        assert f'data-wyjscie-wymiar="{wymiar}"' in strona_pelna


def test_wyjscie_do_mapy_nie_jest_przepisywane(strona):
    """Mapa wojewodztw nie jest Eksploratorem — nie ma wymiaru ani miary."""
    fragment = strona.split('?mapa=1')[1].split('</a>')[0]
    assert 'data-wyjscie-miara' not in fragment


def test_js_przepisuje_adresy_stopek_przy_kazdym_wypelnieniu(js):
    assert 'odswiezStopki' in js
    assert "querySelectorAll('a[data-wyjscie-miara]')" in js
    # Przepisanie ma sie dziac przy kazdym rysowaniu kafelka (petla wypelnij()
    # i kafelek wstawiony w miejscu), a nie raz przy starcie.
    fragment = js.split('function rysujKafelek')[1].split('\n  }\n')[0]
    # Od partii E (punkt E4) z filtrem wykluczen z payloadu, jesli jest.
    assert "odswiezStopki(wezel, wykluczenia.filtr || '')" in fragment
    # Cialo SAMEJ funkcji wypelnij(dane) — nie „pierwsza funkcja o nazwie
    # zaczynajacej sie od wypelnij": od partii E (punkt E3) jest tez
    # wypelnijDymekWykresu.
    assert 'rysujKafelek(wezel, dane)' in \
        js.split('function wypelnij(dane)')[1].split('\n  }\n')[0]


def test_js_sklada_adres_stopki_z_biezacego_stanu(js):
    fragment = js.split('function odswiezStopki')[1].split('\n  }')[0]
    assert "parametry.set('od', stan.od)" in fragment
    assert "parametry.set('do', stan.do)" in fragment
    # Wymiar niesie samo wyjscie — mapy wymiarow kart w stanie juz nie ma.
    assert "getAttribute('data-wyjscie-wymiar')" in fragment
    assert 'stan.wymiary' not in fragment


# --- adnotacje kart, ktore nie sa liczone za okres --------------------------

def test_adnotacje_kart_spoza_okresu_sa_widoczne_zawsze(strona_pelna):
    """„Klienci" i „Naleznosci" NIE sa liczone za wybrany okres, a adnotacja
    o tym pokazywala sie dopiero po wlaczeniu segmentu porownawczego —
    wiekszosc uzytkownikow nigdy go nie wlaczy i odczyta obie karty jako dane
    okresu."""
    for typ in ('klienci', 'naleznosci'):
        fragment = strona_pelna.split(f'data-bez-segmentu="{KLUCZ[typ]}"')[1].split('>')[0]
        assert 'hidden' not in fragment, typ
        assert 'data-zawsze' in fragment, typ


def test_adnotacje_czysto_segmentowe_zostaja_ukryte(strona):
    """Wnioski i lejek SA liczone za okres — ich adnotacja dotyczy wylacznie
    segmentu i ma sie pokazac dopiero z nim."""
    for klucz in ('wnioski', 'lejek'):
        fragment = strona.split(f'data-bez-segmentu="{klucz}"')[1].split('>')[0]
        assert 'hidden' in fragment, klucz
        assert 'data-zawsze' not in fragment, klucz


def test_js_nie_chowa_adnotacji_oznaczonej_jako_stala(js):
    assert "hasAttribute('data-zawsze')" in js


# --- popover filtra ---------------------------------------------------------

def test_popover_ustawia_wymiar_ktory_juz_jest_w_filtrze(js_filtra):
    """Otwarty z gotowym filtrem startowal na pierwszej opcji (Data): user
    widzial chip „Kanal sprzedazy: Sklep", otwieral go i dostawal liste dat
    z niczym zaznaczonym."""
    assert 'juzWybrany' in js_filtra
    assert 'wybor.value = juzWybrany' in js_filtra
    assert js_filtra.index('wybor.value = juzWybrany') < js_filtra.index('wczytajWartosci();\n    wybor.focus();')


def test_popover_zapamietuje_etykiety_wartosci_dla_podgladu(js_filtra):
    """Bez tego podglad sklada sie z SUROWYCH wartosci: user widzi
    „Kanał sprzedaży: shop, personal", klika „Zastosuj" i dostaje chip
    „Kanał sprzedaży: Sklep, Ręczne w BL" — te same dwa jezyki sekunde po
    sobie."""
    assert 'etykietyWartosci' in js_filtra
    assert 'opcje.opisz(wybrane, etykietyWartosci)' in js_filtra


def test_opisz_filtr_uzywa_etykiet_wartosci(js):
    # Cialo opiszFiltr: do pierwszego zamkniecia funkcji na poziomie modulu.
    fragment = js.split('function opiszFiltr')[1].split(chr(10) + '  }')[0]
    assert 'etykietyWartosci' in fragment
    assert 'mapa[w] || w' in fragment


# --- wygasla sesja ----------------------------------------------------------

def test_js_mowi_wprost_o_wygaslej_sesji(js):
    assert 'odp.status === 401' in js
    assert 'Sesja wygasła' in js


# --- jednostki przy liczbach ------------------------------------------------
# Zgloszenie uzytkownika (22.09.2026): „w obecnym widoku tych wykresow doda
# jednostki przy liczbach. Bo nie wiadomo czy to sztuki czy kwota". Najgorszy
# przypadek: karta „Klienci wedlug: liczba zamowien" ma wiersze podpisane
# „1 zam.", „2–3", „4–9", „10+" i kolumne w rodzaju „2 204 223" — czyta sie to
# jak liczbe klientow, a sa to zlotowki.
#
# Zasada: jednostka podpisana RAZ, w naglowku kolumny albo w etykiecie, a nie
# doklejona do kazdej liczby.

# Karta „Klienci według" od partii E (punkt E2) to koło z legendą-tabelą, a nie
# słupki — nagłówki jej kolumn sprawdza test_karta_klientow_* niżej.
KARTY_ZE_SLUPKAMI = ['kanal', 'kanal_rozbicie', 'opiekun',
                     'wojewodztwo', 'dostawa', 'naleznosci', 'wykonczenie',
                     'lejek']


def test_kazdy_kafelek_kpi_niesie_jednostke(strona):
    from modules.reports.analiza_service import JEDNOSTKI_MIAR

    for pole in ('netto', 'objetosc', 'zamowienia', 'srednie_zamowienie', 'cena_za_m3'):
        jednostka = JEDNOSTKI_MIAR[pole]
        assert f'an-etykieta__jednostka">&#160;{jednostka}<' in strona, \
            f'kafelek {pole} bez jednostki {jednostka}'


def test_kazda_karta_ze_slupkami_ma_naglowek_kolumny_z_jednostka(strona_pelna):
    """Nagłowek to jedno miejsce na karte, nie sufiks przy czternastu liczbach."""
    from modules.reports.analiza_service import JEDNOSTKI_MIAR, KOLUMNY_KART

    naglowki = re.findall(r'an-naglowek-kolumn">(.*?)</div>', strona_pelna, re.S)
    assert len(naglowki) == len(KARTY_ZE_SLUPKAMI), \
        f'{len(naglowki)} naglowkow, oczekiwano {len(KARTY_ZE_SLUPKAMI)}'
    for karta in KARTY_ZE_SLUPKAMI:
        miara, podpis = KOLUMNY_KART[karta]
        pasujace = [n for n in naglowki
                    if podpis in n and JEDNOSTKI_MIAR[miara] in n]
        assert pasujace, f'karta {karta}: brak naglowka „{podpis}" z jednostka'


def test_karta_klientow_mowi_wprost_ze_to_zlotowki(strona):
    """Regresja zgloszenia: „2 204 223" przy wierszu „1 zam.".

    Sama kwota bez podpisu czyta sie jak liczba klientow w kubelku. Od partii E
    (punkt E2) pod kolem stoi legenda-tabela: kolumna udzialu podpisana
    jednostka udzialu, kolumna kwoty — „Netto" z jednostka z rejestru.
    """
    from modules.reports.analiza_service import JEDNOSTKI_MIAR

    klucz = KLUCZ['klienci']
    karta = strona.split(f'data-klucz="{klucz}"')[1].split('</section>')[0]
    glowa = karta.split('<thead>')[1].split('</thead>')[0]
    assert f'>{JEDNOSTKI_MIAR["udzial"]}<' in glowa
    assert 'Netto' in glowa and f'&#160;{JEDNOSTKI_MIAR["netto"]}<' in glowa


def test_naglowek_kolumny_nie_jest_wierszem_bo_js_by_go_skasowal(strona, js):
    """rysujWiersze() kasuje wszystkie bezposrednie dzieci ciala karty z klasa
    .an-wiersz. Naglowek z ta klasa znikalby przy pierwszym wypelnieniu
    danymi — czyli zawsze, zanim uzytkownik cokolwiek zobaczy."""
    assert "classList.contains('an-wiersz')" in js
    for naglowek in re.findall(r'<div class="([^"]*an-naglowek-kolumn[^"]*)"', strona):
        assert 'an-wiersz' not in naglowek


def test_slupek_i_wypisana_liczba_karty_uzywaja_tego_samego_pola(js):
    """NIEZMIENNIK dla kazdej karty ze slupkami: liczba obok slupka ma byc
    TA SAMA wielkoscia, po ktorej skalowany jest slupek — inaczej wiersz
    przeczy sam sobie, niezaleznie od tego, co mowi tytul karty.

    Regresja buga (zmierzone na danych produkcyjnych 22.09.2026): karty
    „Sprzedaż netto według: Województwo" i „Dostawa według: Sposób odbioru"
    skalowaly slupek po netto (w.netto / maks), ale wypisywana liczba przez
    opcje `jednaDziesiata` przelaczala sie na w.objetosc — Mazowieckie mialo
    slupek proporcjonalny do 84 419,53 zl netto, a obok stalo „4,8" (m3).
    Test pojedynczej karty by tego nie zlapal — trzeba porownac slupek
    i liczbe W TYM SAMYM wierszu, co robi ponizej.

    `jednaDziesiata` zostalo usuniete jako martwy kod: to byla jedyna
    galaz, ktora mogla rozjechac liczbe ze slupkiem."""
    fragment = js.split('function rysujWiersze')[1].split('function rysujTabeleMiksu')[0]

    # Sama nazwa opcji moze zostac we wspomnieniu w komentarzu (historia buga),
    # ale nie wolno jej uzywac jako dzialajacego kodu — ani jako klucz opcji
    # przekazany do rysujWiersze(), ani jako warunek w samej funkcji.
    assert 'jednaDziesiata:' not in js, \
        'martwa opcja jednaDziesiata miala zniknac z wywolan rysujWiersze'
    assert 'opcje.jednaDziesiata' not in js, \
        'martwa opcja jednaDziesiata miala zniknac z ciala rysujWiersze'

    # Oba wypelnienia paska (baza i segment porownawczy) skaluja sie
    # WYLACZNIE po netto — to jest miara, ktora „niesie" slupek.
    assert 'wyp.style.width = (maks ? (w.netto / maks) * 100' in fragment
    assert 'wypBaza.style.width = (maks ? (w.netto / maks) * 100' in fragment
    assert 'wypPorownanie.style.width = (maks ? (drugi.netto / maks) * 100' in fragment
    # `maks` (skala slupka) tez liczy sie z netto, nigdy z innego pola —
    # inaczej najdluzszy slupek nie musialby odpowiadac najwiekszej liczbie.
    assert re.search(r'if \(w\.netto > maks\)', fragment)

    # Wypisywana liczba: DOKLADNIE to samo pole co slupek, bez warunkowego
    # przelaczania na inna miare (tak jak robil to `jednaDziesiata`).
    assert re.search(
        r"el\('span', 'an-wiersz__wartosc', fmt0\.format\(w\.netto\)\)", fragment), \
        'liczba w kolumnie karty ma czytac w.netto — dokladnie to samo pole co slupek'


def test_kolumny_kart_ze_slupkami_deklaruja_netto_jak_slupek(strona):
    """Niezmiennik po stronie serwera: skoro analiza.js skaluje KAZDY slupek
    po netto (patrz test wyzej), to `KOLUMNY_KART` dla kart wymiarowych ma
    podpisywac kolumne liczb jako netto — inaczej naglowek karty kłamie
    o tym, co faktycznie widac. Karty wojewodztwo/dostawa dostaly tu kiedys
    'objetosc'; regresja tego samego buga co test wyzej, tylko po stronie
    naglowka kolumny zamiast po stronie JS."""
    from modules.reports.analiza_service import KOLUMNY_KART

    # Karty budowane wprost z `_karta()`/`_wiersze_wymiaru` (patrz
    # analiza_service.py) niosa w polu `netto` PRAWDZIWE netto z bazy —
    # dla nich miara zadeklarowana w KOLUMNY_KART musi byc 'netto'.
    for karta in ('kanal', 'kanal_rozbicie', 'opiekun', 'wojewodztwo',
                  'dostawa', 'wykonczenie'):
        miara, _ = KOLUMNY_KART[karta]
        assert miara == 'netto', f'karta {karta}: slupek niesie netto, naglowek podpisuje {miara}'

    # Wojewodztwo i dostawa maja ten sam tytul-wzorzec „Sprzedaż netto
    # według:” / brzmienie „Dostawa według:” co karty siostrzane (kanal,
    # opiekun) — kolumna ma wiec wygladac tak samo: „Netto” + jednostka zl.
    assert 'Sprzedaż netto według:' in strona
    assert 'Dostawa według:' in strona


def test_js_nie_ma_wlasnej_listy_jednostek(js):
    """Waluta przychodzi w payloadzie (`dane.jednostki`). Wpisana tutaj byłaby
    drugim zrodlem prawdy obok naglowkow, ktore wypisuje szablon."""
    assert 'zł' not in js, 'jednostka waluty wpisana na sztywno w JavaScripcie'
    assert 'jednostki = dane.jednostki' in js


def test_js_oddziela_jednostke_od_cyfr_i_nie_lamie_wiersza(js):
    """Liczba jest monospace'em, jednostka tekstem — stad osobny span. Spacja
    miedzy nimi jest nierozdzielajaca."""
    assert "el('span', 'an-jednostka', '\u00a0' + tekst)" in js


def test_css_ma_style_jednostek_i_nie_koloruje_ich_na_czerwono():
    """Czerwien jest zarezerwowana dla bledow (--bad). Jednostka to podpis."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    for klasa in ('.an-jednostka', '.an-etykieta__jednostka', '.an-naglowek-kolumn'):
        assert klasa in css, f'brak stylu {klasa}'
    for klasa in ('.an-jednostka', '.an-etykieta__jednostka',
                  '.an-naglowek-kolumn__jednostka'):
        blok = css.split(klasa + ' {', 1)[1].split('}', 1)[0]
        assert '--bad' not in blok and '#B33A2B' not in blok


def test_jednostka_jest_krojem_tekstowym_a_nie_monospace():
    """Zasada makiety: IBM Plex Mono na cyfry, IBM Plex Sans na tekst.
    .an-jednostka siedzi wewnatrz wezla monospace'owego, wiec musi jawnie
    wrocic do kroju tekstowego."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    blok = css.split('.an-jednostka {', 1)[1].split('}', 1)[0]
    assert "font-family: 'IBM Plex Sans'" in blok


def test_tabela_miksu_bierze_jednostki_z_rejestru(strona):
    """Ta karta miala jednostki w naglowkach od poczatku i jest wzorcem dla
    pozostalych — ale wpisane na sztywno rozjechalyby sie z Eksploratorem."""
    from modules.reports.analiza_service import JEDNOSTKI_MIAR

    assert f'>{JEDNOSTKI_MIAR["objetosc"]}</th>' in strona
    assert f'>{JEDNOSTKI_MIAR["cena_za_m3"]}</th>' in strona


def test_os_pionowa_wykresu_trendu_ma_podpisana_jednostke(strona):
    """Podzialka wykresu to „400k" — bez podpisu nie wiadomo, czego jest to
    400 tysiecy."""
    assert 'an-legenda__jednostka' in strona
    assert 'oś pionowa: tys.' in strona


def test_kolumna_procentowa_lejka_jest_podpisana_z_rejestru(strona):
    """Druga kolumna liczb lejka to udzial stopnia w stopniu pierwszym.
    Goła „30" obok „1 365" wyglada jak druga liczba sztuk."""
    from modules.reports.analiza_service import JEDNOSTKI_MIAR

    naglowek = [n for n in re.findall(r'an-naglowek-kolumn">(.*?)</div>', strona, re.S)
                if 'Wyceny' in n]
    assert naglowek, 'karta lejka bez naglowka kolumn'
    assert JEDNOSTKI_MIAR['wycen'] in naglowek[0]
    assert JEDNOSTKI_MIAR['udzial'] in naglowek[0]


# --- karta lejka ------------------------------------------------------------
# Zgloszenie uzytkownika (23.09.2026): „brakuje mi tutaj statystyk z wycen, ile
# zrobionych, ile zamowionych ile z nich zostalo oplaconych - przeszlo do
# realizacji i innych statystyk". Karta miala dwa stopnie i wykres konwersji
# miesiecznej; ma piec stopni, trzy statystyki wycen i selektor podzialu.


def test_karta_lejka_ma_selektor_podzialu_w_opakowaniu(strona):
    """Selektor podzialu przechodzi przez to samo opakowanie co kazdy inny.

    Bez .an-sel-opak przezroczysty <select> z inset:0 rozlewa sie na cale okno
    i zabija klikalnosc CALEJ strony — patrz historia buga przy tescie
    struktury nizej.
    """
    soup = BeautifulSoup(strona, 'html.parser')
    wybor = soup.select_one('select.an-sel[data-selektor-lejka]')
    assert wybor is not None, 'karta lejka bez selektora podzialu'
    assert 'an-sel-opak' in (wybor.parent.get('class') or [])
    assert wybor.parent.select_one('.an-sel-etykieta') is not None


def test_domyslna_opcja_podzialu_zgadza_sie_z_serwerem(strona):
    """Szkielet niesie opcje domyslna, zeby kontrolka byla czytelna od
    pierwszej klatki — ale jej napis MUSI byc tym samym napisem, ktory
    dolozy analiza.js z payloadu. Dwie wersje tego samego napisu rozjechalyby
    sie przy pierwszej zmianie brzmienia."""
    from modules.reports.analiza_service import wymiary_lejka

    domyslna = wymiary_lejka()[0]['etykieta']
    soup = BeautifulSoup(strona, 'html.parser')
    wybor = soup.select_one('select.an-sel[data-selektor-lejka]')
    assert wybor.get_text(strip=True) == domyslna
    assert wybor.parent.select_one('.an-sel-etykieta').get_text(strip=True) == domyslna


def test_selektor_podzialu_nie_jest_selektorem_wymiaru_karty(strona):
    """`data-selektor` znaczy „wymiar karty" — trafia do adresu i do zapytania
    o dane. Podzial lejka nie jest wymiarem karty: wszystkie warianty przychodza
    policzone w jednym payloadzie, a trasa /api/analytics zna wylacznie klucze
    z DOMYSLNE_WYMIARY i nowego parametru nie zwalidowalaby."""
    from modules.reports.analiza_service import DOMYSLNE_WYMIARY

    soup = BeautifulSoup(strona, 'html.parser')
    wybor = soup.select_one('select.an-sel[data-selektor-lejka]')
    assert wybor.get('data-selektor') is None
    assert 'lejek' not in DOMYSLNE_WYMIARY


def test_statystyki_lejka_maja_jednostki_z_rejestru(strona):
    """Trzy liczby pod lejkiem: dwie kwoty i mediana w dniach. Bez podpisu
    „3 147" obok „3 083" wyglada jak dwie liczby wycen."""
    from modules.reports.analiza_service import JEDNOSTKI_MIAR

    for miara in ('wartosc_wyceny', 'czas_do_zamowienia'):
        jednostka = JEDNOSTKI_MIAR[miara]
        assert f'an-etykieta__jednostka">&#160;{jednostka}<' in strona, miara
    for sciezka in ('lejek.srednia_wycena', 'lejek.srednia_zamowiona',
                    'lejek.mediana_dni'):
        assert f'data-pole="{sciezka}"' in strona


def test_tabela_podzialu_jest_schowana_dopoki_nikt_nie_wybierze(strona):
    """Domyslnie karta pokazuje sam lejek i ma te sama wysokosc co przed
    rozbudowa — rzad siatki trzymaja cztery karty, a najwyzsza wyznacza
    wysokosc wszystkich."""
    fragment = strona.split('data-podzial="lejek"')[1].split('>')[0]
    assert 'hidden' in fragment


def test_podzial_mowi_wprost_ze_idzie_po_atrybutach_wyceny(strona):
    """Karty obok grupuja po kolumnach ZAMOWIENIA, ta po kolumnach WYCENY.
    Etykiety juz tego nie myla („Autor wyceny", nie „Opiekun"), ale liczby
    stoja obok siebie na jednym ekranie i jedno zdanie taniej kosztuje niz
    zestawienie ich ze soba przez pomylke.

    Zdanie siedzi W BLOKU PODZIALU, wiec pokazuje sie dokladnie wtedy, gdy
    na ekranie sa liczby, ktorych dotyczy — i nie podnosi wysokosci karty
    w stanie domyslnym."""
    # Parsujemy DRZEWO, nie tniemy tekstu na pierwszym „</div>": blok podzialu
    # ma w srodku zagniezdzony kadr przewijania rozwinietego ogona, wiec ciecie
    # po napisie urywa go w polowie tabeli (23.09.2026).
    soup = BeautifulSoup(strona, 'html.parser')
    blok = soup.select_one('[data-podzial="lejek"]')
    assert blok is not None, 'brak bloku podzialu lejka'
    assert 'Podział idzie po atrybutach wyceny, nie zamówienia.' in blok.get_text()
    assert blok.select_one('.an-przypis') is not None
    # NIE .an-bez-segmentu: analiza.js chowa wszystko z tym atrybutem,
    # a ten przypis ma byc widoczny zawsze razem z tabela.
    assert blok.select_one('[data-bez-segmentu]') is None


def test_przypis_jest_wyciszony_a_nie_czerwony():
    """Przypis to podpis, nie ostrzezenie. Czerwien zostaje dla bledow."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    blok = css.split('.an-przypis {', 1)[1].split('}', 1)[0]
    assert 'var(--muted-3)' in blok
    assert '--bad' not in blok and '#B33A2B' not in blok


def test_uwaga_lejka_nie_jest_czerwona(strona):
    """Czerwien zostaje dla bledow i dla ostrzezenia o wiarygodnosci salda.
    Granica dowiazania wycen do sprzedazy to informacja, nie awaria."""
    cialo = strona.split('data-cialo="lejek"')[1].split('an-karta__stopka')[0]
    assert 'an-info' in cialo
    assert 'an-ostrzezenie' not in cialo
    assert 'data-pole="lejek.uwaga"' in cialo


def test_js_rysuje_stopnie_lejka_z_payloadu_a_nie_liczy_ich(js):
    """Slupek to udzial policzony na SERWERZE, liczba obok to ten sam stopien
    w sztukach. Przeliczanie udzialu w przegladarce byloby druga regula
    zaokraglenia obok tej z analytics._procent."""
    fragment = js.split('function rysujLejek')[1].split('function rysujPodzialLejka')[0]
    assert 'dane.lejek.stopnie.forEach' in fragment
    assert "wyp.style.width = stopien.udzial + '%'" in fragment
    assert 'fmt0.format(stopien.liczba)' in fragment
    # Zadnego dzielenia ani mnozenia na danych lejka.
    assert '/ dane.lejek' not in fragment and '* 100' not in fragment


def test_przelaczenie_podzialu_lejka_nie_odpytuje_serwera(js):
    """Wszystkie podzialy przychodza w jednym payloadzie, wiec zmiana wyboru
    ma byc natychmiastowa. Wywolanie ustawParametry() dolozyloby zadanie
    i parametr do adresu, ktorego trasa i tak nie zna."""
    fragment = js.split('function podepnijSelektorLejka')[1].split('\n  }')[0]
    assert 'rysujPodzialLejka(ostatnieDane)' in fragment
    assert 'ustawParametry' not in fragment
    assert 'zaladuj' not in fragment


def test_js_przepisuje_widoczna_etykiete_po_zmianie_selektora(js):
    """Etykieta selektora jest osobnym <span> pod przezroczystym <select>
    (patrz .an-sel-opak). Bez przepisania karta pokazuje nowe dane pod STARA
    nazwa wymiaru az do pelnego przeladowania strony."""
    assert 'function ustawEtykieteSelektora' in js
    fragment = js.split('function podepnijSelektory')[1].split('\n  }')[0]
    assert 'ustawEtykieteSelektora(zdarzenie.target)' in fragment

# --- niezmiennik: kazdy select.an-sel siedzi w opakowaniu -------------------
# Zgloszenie uzytkownika (22.09.2026): na cala strone nie dalo sie w nic
# kliknac, kursor wszedzie byl "rekawiczka". Przyczyna: karty "Klienci wedlug:"
# i "Naleznosci wedlug:" mialy <select class="an-sel"> wpisany wprost, z
# pominieciem makra selektor() (Zadanie z 55-72) — ich rodzicem byl goly
# .an-karta__wymiar (position: static), nie .an-sel-opak (position: relative).
# .an-sel ma w analiza.css `position: absolute; inset: 0` (patrz linie
# 146-150) — bez pozycjonowanego rodzica inset:0 rozwiazuje sie wzgledem
# POCZATKOWEGO BLOKU ZAWIERAJACEGO, czyli okna, wiec kazdy z tych dwoch
# selektow mial rozmiar 1440x900 i przechwytywal wszystkie kliknieca na
# stronie. Select mial poprawne opcje i przechodzil kazda dotychczasowa
# asercje obecnosci tresci — strona byla mimo to calkowicie martwa. Zaden
# test tresci tego nie widzi, bo HTML wyglada poprawnie; trzeba sprawdzic
# STRUKTURE (kto jest rodzicem), nie sama obecnosc elementu.

def test_kazdy_select_an_sel_ma_rodzica_an_sel_opak(strona_pelna):
    soup = BeautifulSoup(strona_pelna, 'html.parser')
    selekty = soup.select('select.an-sel')
    # Dziewiec kart ma selektor: osiem wymiarowych (kanal, opiekun, mix,
    # klienci, wojewodztwo, naleznosci, wykonczenie, dostawa) plus selektor
    # PODZIALU na karcie lejka. "Wnioski" selektora nie maja.
    assert len(selekty) == 9, f'oczekiwano 9 selektorow, znaleziono {len(selekty)}'
    for select in selekty:
        klucz = select.get('data-selektor', '?')
        rodzic = select.parent
        klasy_rodzica = rodzic.get('class') or [] if rodzic is not None else []
        assert 'an-sel-opak' in klasy_rodzica, (
            f'select[data-selektor="{klucz}"] nie ma bezposredniego rodzica '
            '.an-sel-opak — bez niego inset:0 rozwiazuje sie wzgledem okna '
            'i select przykrywa cala strone (patrz historia buga wyzej)'
        )


def test_an_karta__wymiar_ma_wlasny_kontekst_pozycjonowania():
    """Siatka bezpieczenstwa w CSS: .an-karta__wymiar (przodek kazdego
    .an-sel-opak) ma miec position: relative, zeby nawet gdyby ktos kiedys
    znowu dopisal select.an-sel bez opakowania .an-sel-opak, inset:0 trafil
    w najblizszego pozycjonowanego przodka zamiast w okno przegladarki."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    blok = css.split('.an-karta__wymiar {', 1)[1].split('}', 1)[0]
    assert 'position: relative' in blok


# --- niezmiennik: element absolutny ma pozycjonowanego przodka w kafelku -----
# Weryfikacja partii E (W1): podpis „tylko dla czytnika" w legendzie koła
# Klienci (.an-ukryte, `position: absolute`) nie miał pozycjonowanego przodka.
# Blokiem zawierającym był <body>, więc element uciekał spod przewijania
# #analiza i wydłużał przewijanie CAŁEGO dokumentu: przy 1366x768 kółko myszy
# nad paskiem bocznym przesuwało stronę o 248 px, a pasek z okresem i polami
# wykluczeń znikał nad oknem. Ta sama klasa błędu co select.an-sel wyżej:
# HTML wygląda poprawnie, a zepsuta jest STRUKTURA — kto jest przodkiem.

def _selektory_pozycjonowane(css):
    """Selektory reguł z `position: relative|absolute|sticky|fixed` (bez
    reguł w @media i z pseudoklasami — tych BeautifulSoup nie dopasuje)."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    wynik = []
    for blok in css.split('}'):
        if '{' not in blok:
            continue
        selektory, cialo = blok.rsplit('{', 1)
        if not re.search(r'position:\s*(relative|absolute|sticky|fixed)', cialo):
            continue
        for selektor in selektory.split(','):
            selektor = selektor.strip()
            if selektor and '@' not in selektor and ':' not in selektor:
                wynik.append(selektor)
    return wynik


def test_podpis_dla_czytnika_ma_pozycjonowanego_przodka_w_kafelku(strona_pelna):
    soup = BeautifulSoup(strona_pelna, 'html.parser')
    pozycjonowane = set()
    for selektor in _selektory_pozycjonowane(open(SCIEZKA_CSS, encoding='utf-8').read()):
        pozycjonowane.update(id(e) for e in soup.select(selektor))

    ukryte = soup.select('.an-ukryte')
    assert ukryte, 'pulpit pełny ma legendę koła klientów z podpisem .an-ukryte'
    for element in ukryte:
        przodek, znaleziony = element.parent, False
        while przodek is not None and not przodek.has_attr('data-kafelek'):
            if id(przodek) in pozycjonowane:
                znaleziony = True
                break
            przodek = przodek.parent
        assert znaleziony, (
            f'.an-ukryte „{element.get_text()}" nie ma pozycjonowanego przodka '
            'wewnątrz kafelka — `position: absolute` rozwiąże się względem '
            '<body> i wydłuży przewijanie całego dokumentu (historia wyżej)')


def test_szesc_dzialajacych_kart_nadal_uzywa_makra_selektor(strona):
    """Regresja na wzor: szesc kart, ktore od poczatku dzialaly, ma nadal
    przechodzic przez makro selektor() (linie 55-72 szablonu) — naprawa dwoch
    zepsutych kart nie miala dotykac ich znacznika."""
    soup = BeautifulSoup(strona, 'html.parser')
    for typ in ('kanal', 'opiekun', 'mix', 'wojewodztwo', 'wykonczenie', 'dostawa'):
        klucz = KLUCZ[typ]
        select = soup.select_one(f'select.an-sel[data-selektor="{klucz}"]')
        assert select is not None, f'brak selektora {klucz}'
        etykieta = select.parent.select_one('.an-sel-etykieta')
        assert etykieta is not None, f'karta {klucz}: opakowanie bez .an-sel-etykieta'


# --- regresja z przegladu (fala 3: dashboard) --------------------------------

def test_kolor_segmentu_porownawczego_rozni_sie_od_koloru_kanalu_sklep():
    """KRYTYCZNE 2: KOLORY_KANALU.shop (analiza.js) i
    .an-wiersz__wypelnienie--porownanie (analiza.css) byly TYM SAMYM hexem
    (#0F7D94, var(--c-teal)) — na karcie kanalow, przy wlaczonym segmencie
    porownawczym, pasek "Sklep" i pasek serii porownawczej byly nie do
    odroznienia. "Sklep" zostaje #0F7D94 (Main.dc.html:213, makieta wiazaca),
    wiec to kolor porownania musial sie przesunac."""
    js = open(SCIEZKA_JS, encoding='utf-8').read()
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    assert "KOLORY_KANALU.shop = '#0F7D94'" in js or "shop: '#0F7D94'" in js, \
        'Sklep ma zostac #0F7D94 — to kolor porownania mial sie przesunac, nie ten'
    fragment = css.split('.an-wiersz__wypelnienie--porownanie {', 1)[1].split('}', 1)[0]
    assert '#0F7D94' not in fragment
    assert 'var(--c-teal)' not in fragment, \
        'porownanie ma wlasny kolor, nie--c-teal (ten sam hex co kanal Sklep)'


def test_kolor_segmentu_porownawczego_jest_spojny_we_wszystkich_miejscach_css():
    """Chip, pasek w wierszu, druga liczba w KPI i druga wartosc w
    tabeli/legendzie/dymku mapy maja WSZĘDZIE ten sam kolor porownania —
    inaczej "ta sama etykieta" (tu: rola "segment porownawczy") znaczylaby
    co innego w kazdym z tych miejsc."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    for selektor in ('.an-chip--porownanie {', '.an-chip--porownanie .an-chip__kropka {',
                     '.an-wiersz__wypelnienie--porownanie {', '.an-liczba--porownanie {',
                     '.an-wartosc--porownanie {'):
        fragment = css.split(selektor, 1)[1].split('}', 1)[0]
        assert 'var(--c-indygo' in fragment, f'{selektor} nie uzywa nowej palety porownania'
        assert '--c-teal' not in fragment, f'{selektor} nadal odwoluje sie do --c-teal'


def test_przypis_naleznosci_nie_obiecuje_kafelka_ktorego_nie_ma(js):
    """WAZNE 3: przypis mowil "... dają saldo z KPI powyżej", a kafelek KPI
    "Saldo" nie istnieje na dashboardzie — petla kafelkow w dashboard.html
    renderuje tylko netto/objetosc/zamowienia/srednie_zamowienie/cena_za_m3.
    Przypis ma mowic prawde o tym, co jest na ekranie."""
    assert 'z KPI powyżej' not in js
    assert 'dają rzeczywiste saldo zamówień' in js


def test_dashboard_nie_ma_kafelka_kpi_saldo(strona):
    """Uzupelnienie powyzszego: potwierdza wprost, ze na ekranie NIE MA
    kafelka KPI 'Saldo', do ktorego przypis mogl sie odwolywac."""
    fragment = strona.split('an-kpi">', 1)[1].split('an-wykres-kadr', 1)[0]
    assert 'data-pole="kpi.saldo"' not in fragment
    assert '>Saldo<' not in fragment


# --- regresja z przegladu (fala 3): zaokraglanie liczb w przegladarce -------

def test_js_formatuje_liczby_tak_samo_jak_serwer_formatuj_liczbe(js):
    """WAZNE 7: Intl.NumberFormat domyslnie zaokragla „od zera" (2,5 -> 3),
    a serwerowe formatuj_liczbe (Python Decimal) zaokragla do parzystej
    (2,5 -> 2) — ta sama liczba mogla wyjsc inaczej w kafelku KPI (JS) niz
    w zdaniu wniosku ponizej (serwer), np. dane.kpi.srednie_zamowienie
    i dane.kpi.zamowienia, ktore _wniosek_srednie sklada przez
    formatuj_liczbe. roundingMode: 'halfEven' zrownuje obie strony."""
    for zmienna in ('fmt0', 'fmt1', 'fmt2'):
        definicja = js.split(f'var {zmienna} = new Intl.NumberFormat', 1)[1].split(');', 1)[0]
        assert "roundingMode: 'halfEven'" in definicja, \
            f'{zmienna} nie dostal tej samej reguly zaokraglania co serwer'


def test_js_grupuje_tysiace_tak_samo_jak_serwer_formatuj_liczbe(js):
    """Porządki końcowe, punkt 3h. Polska reguła Intl grupuje dopiero od
    pięciu cyfr, więc karta wykończeń pisała „+2027,4% wobec surowego", a
    serwerowe formatuj_liczbe „2 027,4". Każdy formatter liczb pulpitu
    wymusza grupowanie (`useGrouping: 'always'`)."""
    from decimal import Decimal
    from modules.reports.analiza_service import formatuj_liczbe
    assert formatuj_liczbe(Decimal('2027.4'), 1) == '2 027,4'
    for zmienna in ('fmt0', 'fmt1', 'fmt2'):
        definicja = js.split(f'var {zmienna} = new Intl.NumberFormat', 1)[1].split(');', 1)[0]
        assert "useGrouping: 'always'" in definicja, zmienna


def test_js_zmiana_procentowa_ma_spacje_tysiecy():
    """Dowód na żywym silniku: `zmianaNaTekst` z analiza.js wykonany razem ze
    swoim formatterem daje „+2 027,4%" (spacja niełamiąca, jak w całym Intl).
    Wymaga Node — w obrazie dockera go nie ma, więc tam test się pomija."""
    import json
    import subprocess

    js = open(os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'analiza.js'),
              encoding='utf-8').read()
    formatter = 'var fmt1 = new Intl.NumberFormat' + \
        js.split('var fmt1 = new Intl.NumberFormat', 1)[1].split(');', 1)[0] + ');'
    funkcja = 'function zmianaNaTekst(' + \
        js.split('function zmianaNaTekst(', 1)[1].split('\n  }\n', 1)[0] + '\n  }'
    skrypt = (formatter + funkcja + 'console.log(JSON.stringify(['
              'zmianaNaTekst(2027.4), zmianaNaTekst(-1234.5), zmianaNaTekst(84.7)]));')
    try:
        wynik = subprocess.run([os.environ.get('NODE_BIN', 'node'), '-e', skrypt],
                               capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, OSError):
        pytest.skip('Node niedostepny w tym srodowisku')
    if wynik.returncode != 0:
        pytest.skip(f'silnik JS bez Intl NumberFormat v3: {wynik.stderr}')
    assert json.loads(wynik.stdout) == ['+2 027,4%', '−1 234,5%', '+84,7%']


def test_js_zaokragla_polowki_tak_samo_jak_python_decimal():
    """Dowod na konkretnej liczbie, nie tylko na obecnosci opcji: 2,5 ma dac
    '2' (jak Python Decimal), nie '3' (domyslne zachowanie Intl bez
    roundingMode). Wymaga Node — pomijamy cicho, jesli go nie ma (docker
    obrazu tego testu nie ma, ale lokalny dev najczesciej tak)."""
    import json
    import subprocess

    sciezka_node = os.environ.get('NODE_BIN', 'node')
    skrypt = (
        "var f = new Intl.NumberFormat('pl-PL', "
        "{maximumFractionDigits: 0, roundingMode: 'halfEven'});"
        "console.log(JSON.stringify([f.format(2.5), f.format(3.5)]));"
    )
    try:
        wynik = subprocess.run([sciezka_node, '-e', skrypt],
                               capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, OSError):
        pytest.skip('Node niedostepny w tym srodowisku')
    if wynik.returncode != 0:
        pytest.skip(f'silnik JS bez roundingMode (Intl NumberFormat v3): {wynik.stderr}')
    assert json.loads(wynik.stdout) == ['2', '4'], \
        'roundingMode: halfEven ma dac te sama zaokraglenie, co Python Decimal'


# --- selektory kart kubelkowych (zgloszenie: „dropdown sie nie rozwija") -----

def test_selektory_klientow_i_naleznosci_nie_sa_juz_wylaczone(strona_pelna):
    """Zgloszenie uzytkownika 23.09.2026: „dropdown na »Klienci według« nie
    rozwija się". Obie kontrolki mialy jedna opcje i atrybut `disabled`,
    a wygladaly dokladnie jak siedem dzialajacych selektorow obok.

    Naprawa polega na daniu im PRAWDZIWYCH wymiarow, a nie na schowaniu
    kontrolki — uzytkownik planuje uklad, w ktorym ta sama karta wystepuje
    kilka razy z roznymi wymiarami, wiec musi umiec wymiar zmieniac."""
    soup = BeautifulSoup(strona_pelna, 'html.parser')
    for typ, domyslna in (('klienci', 'Liczba zamówień'),
                          ('naleznosci', 'Wiek zamówienia')):
        klucz = KLUCZ[typ]
        select = soup.select_one('select.an-sel[data-selektor="%s"]' % klucz)
        assert select is not None, 'brak selektora %s' % klucz
        assert not select.has_attr('disabled'), \
            'selektor %s nadal wylaczony — nie da sie go otworzyc' % klucz
        opcje = [o.get_text(strip=True) for o in select.select('option')]
        assert len(opcje) > 1, 'selektor %s nadal ma jedna opcje' % klucz
        assert opcje[0] == domyslna, 'domyslna opcja karty %s ma zostac' % klucz
        # Opakowanie jest OBOWIAZKOWE — patrz historia buga przy
        # test_kazdy_select_an_sel_ma_rodzica_an_sel_opak.
        assert 'an-sel-opak' in (select.parent.get('class') or [])


def test_selektory_kart_kubelkowych_maja_wlasna_wezsza_liste(strona_pelna):
    """Rejestr ma 18 prostych wymiarow, ale gatunek czy grubosc opisuja deske,
    nie klienta — a saldo, grupowane po kolumnie pozycji, powielaloby sie przez
    ich liczbe. Obie karty maja wiec WLASNA liste, wezsza niz pozostale."""
    from modules.reports.analiza_service import WYMIARY_KLIENTOW, WYMIARY_NALEZNOSCI
    from modules.reports.fields import POLA

    soup = BeautifulSoup(strona_pelna, 'html.parser')
    oczekiwane = {'klienci': WYMIARY_KLIENTOW, 'naleznosci': WYMIARY_NALEZNOSCI}
    for typ, nazwy in oczekiwane.items():
        klucz = KLUCZ[typ]
        select = soup.select_one('select.an-sel[data-selektor="%s"]' % klucz)
        wartosci = [o.get('value') for o in select.select('option')]
        assert wartosci[1:] == list(nazwy), klucz
        etykiety = [o.get_text(strip=True) for o in select.select('option')]
        # ETYKIETY z rejestru — „Opiekun" znaczy tu to samo, co gdzie indziej.
        assert etykiety[1:] == [POLA[n].etykieta for n in nazwy], klucz
        # Wymiary, ktore na tej karcie nie maja sensu, NIE wchodza na liste.
        assert 'thickness_cm' not in wartosci and 'wood_species' not in wartosci


def test_naglowek_kolumny_kart_kubelkowych_jest_przepisywalny(strona_pelna, js):
    """Podpis kolumny karty kubelkowej jedzie z payloadu, wiec musi dac sie
    przepisac. Bez uchwytow `data-naglowek-*` JavaScript nie mialby czego
    przepisac.

    Karta klientow od partii E (punkt E2) ma w kazdym wymiarze te sama
    kolumne — „Netto" pod kolem, w legendzie-tabeli wypisanej przez serwer
    (test_karta_klientow_mowi_wprost_ze_to_zlotowki) — wiec uchwytu do
    przepisywania juz nie potrzebuje."""
    soup = BeautifulSoup(strona_pelna, 'html.parser')
    for klucz in ('naleznosci',):
        blok = soup.select_one('[data-naglowek="%s"]' % klucz)
        assert blok is not None, 'karta %s bez uchwytu naglowka' % klucz
        assert blok.select_one('[data-naglowek-podpis]') is not None
        assert blok.select_one('[data-naglowek-jednostka]') is not None
    assert 'rysujNaglowekKolumny' in js
    # Jednostka NIE jest wpisana w JavaScripcie — przychodzi w naglowku
    # z payloadu, tak samo jak wszedzie indziej na tej stronie.
    assert 'naglowek.jednostka' in js


def test_adnotacje_kart_kubelkowych_biora_tresc_z_payloadu(strona_pelna, js):
    """Kubelki licza sie z calej historii (klienci) albo na dzis (naleznosci),
    a przekroj po wymiarze — za wybrany okres. Jedno zdanie dla obu stanow
    musialoby jednemu z nich klamac, wiec tresc jedzie z serwera."""
    soup = BeautifulSoup(strona_pelna, 'html.parser')
    for typ in ('klienci', 'naleznosci'):
        klucz = KLUCZ[typ]
        akapit = soup.select_one('[data-bez-segmentu="%s"]' % klucz)
        assert akapit.get('data-pole') == '%s.uwaga' % klucz
        # Wariant DOMYSLNY stoi w szablonie, zeby adnotacja byla prawdziwa
        # takze przed przyjsciem danych.
        assert akapit.get_text(strip=True)
    # Tresc z payloadu karty (`karta.uwaga`), wstawiona w pole TEGO kafelka.
    fragment = js.split('function rysujKarteKubelkowa')[1].split('\n  }')[0]
    assert "klucz + '.uwaga', karta.uwaga" in fragment


# --- rozwijany wiersz „Pozostale (N)" ---------------------------------------

def test_js_rozwija_ogon_bez_liczenia_czegokolwiek(js):
    """Zgloszenie uzytkownika: „Jak piszesz opcje »Pozostałe« to zróbmy ją
    klikalną, która rozwinie resztę danych".

    Ogon PRZYCHODZI JUZ POLICZONY z serwera (klucz `ogon` w payloadzie), wiec
    rozwiniecie to wylacznie zdjecie `hidden`. Gdyby przegladarka sumowala
    cokolwiek sama, zlamalaby zasade z naglowka tego pliku."""
    fragment = js.split('function podepnijRozwijanie')[1].split('\n  }')[0]
    assert 'aria-expanded' in fragment
    assert 'element.hidden = !rozwiniete' in fragment
    # Ani jednego dodawania: to ma byc pokazanie gotowych wierszy, nie liczenie.
    assert 'reduce(' not in fragment
    assert '+=' not in fragment


def test_wiersz_zbiorczy_jest_przyciskiem_a_nie_samym_napisem(js):
    """Enter i spacja maja dzialac, fokus ma byc widoczny, a czytnik ekranu ma
    dostac `aria-expanded`. Natywny <button> daje to wszystko za darmo —
    <div> z nasluchem wymagalby recznego odtwarzania kazdej z tych rzeczy."""
    fragment = js.split('function etykietaRozwijana')[1].split('\n  }')[0]
    assert "el('button'" in fragment
    assert "przycisk.type = 'button'" in fragment
    assert "setAttribute('aria-expanded', 'false')" in fragment


def test_js_obsluguje_enter_i_spacje_na_wierszu_zbiorczym(js):
    """Wprost, a nie tylko natywnie: preventDefault() gasi domyslna aktywacje
    przycisku, wiec przelaczenie dzieje sie raz i tylko raz."""
    fragment = js.split('function podepnijRozwijanie')[1].split('\n  }')[0]
    assert "klawisz !== 'Enter'" in fragment
    assert "klawisz !== ' '" in fragment
    assert 'preventDefault()' in fragment


def test_kazda_karta_z_ogonem_rysuje_go_w_przegladarce(js):
    """Cztery rozne sposoby rysowania listy na tej stronie (slupki, tabela
    miksu, legenda wykonczen, tabela podzialu lejka) — kazdy musi umiec
    rozwinac ogon, inaczej „Pozostale" znaczy co innego na roznych kartach."""
    for funkcja in ('rysujWiersze', 'rysujTabeleMiksu', 'rysujLegendeWykonczenia',
                    'rysujPodzialLejka'):
        fragment = js.split('function %s' % funkcja)[1].split('\n  }\n')[0]
        assert 'podepnijRozwijanie' in fragment, funkcja
        assert 'ogon' in fragment, funkcja


def test_rysuj_wiersze_kasuje_takze_pojemnik_ogona(js):
    """rysujWiersze() czysci karte przed kazdym wypelnieniem. Gdyby kasowal
    same .an-wiersz, przy kazdym odswiezeniu zostawalby na karcie kolejny
    pojemnik rozwinietego ogona."""
    fragment = js.split('function rysujWiersze')[1].split('function rysujTabeleMiksu')[0]
    assert "classList.contains('an-ogon')" in fragment


def test_css_ma_style_rozwijanego_ogona():
    """Wiersz ma wygladac i zachowywac sie jak cos klikalnego (kursor, stan po
    najechaniu, widoczny fokus), a rozwinieta lista ma sie PRZEWIJAC w obrebie
    karty — inaczej rzad siatki skakalby o kilkaset pikseli."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    assert '.an-rozwin {' in css
    assert '.an-rozwijalny:hover' in css
    assert '.an-rozwin:focus-visible' in css

    # Zgłoszenie użytkownika 23.09.2026: po rozwinięciu „Pozostałe" wysokość
    # rzędu siatki ma zostać IDENTYCZNA, a wolne miejsce karty ma się
    # wypełnić. Weryfikacja poprawek (znalezisko 3): dawny region z limitem
    # 132/168 px podnosił rząd o ten limit, gdy karta nie miała wolnego
    # miejsca (opiekun przy 1440 px: 276 → 415 px, kanał obok pusty).
    #
    # Teraz przewija się CAŁE CIAŁO karty (górne wiersze razem z ogonem):
    # `flex-basis: 0` + `min-height` = wysokość ciała ZWINIĘTEGO, więc do
    # wysokości rzędu wchodzi dokładnie to, co przed rozwinięciem; wolne
    # miejsce karta bierze przez `flex-grow`, a nadmiar się przewija.
    cialo = _regula(css, '.an-kafelek:not(.an-kafelek--pomiar) .an-karta__cialo:has('
                         '.an-ogon:not([hidden]), .an-kadr-listy--rozwiniety)')
    for deklaracja in ('flex-basis: 0', 'min-height: var(--wys-zwinieta', 'overflow-y: auto',
                       'overflow-x: hidden'):
        assert deklaracja in cialo, deklaracja
    # Tylko w siatce WIELOKOLUMNOWEJ (powyżej 900 px, ten sam próg co
    # `.an-siatka`). W jednej kolumnie rząd to sama karta — nie ma sąsiadów,
    # którzy staliby puści, a przewijane pudełko w karcie na telefonie
    # łapałoby przewijanie strony. Tam karta rośnie o ogon.
    blok = css.split('@media (min-width: 901px) {', 1)
    assert len(blok) == 2, 'reguła rozwinięcia poza zapytaniem o szerokość'
    assert blok[1].index('.an-kafelek:not(.an-kafelek--pomiar) .an-karta__cialo:has(') \
        < blok[1].index('\n}')
    assert '@media (max-width: 900px) {\n  .an-siatka { grid-template-columns: 1fr; }' in css
    bez_komentarzy = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    # Region ogona nie ma już WŁASNEGO limitu wysokości ani kolumn flex
    # przodków — to one podnosiły rząd.
    for zakazane in ('--wys-regionu', 'calc-size', 'display: contents'):
        assert zakazane not in bez_komentarzy, zakazane
    # Tryb pomiaru: karta o wysokości treści, ogony schowane, bez reguły
    # rozwinięcia — tak analiza.js czyta wysokość ciała zwiniętego.
    assert 'align-self: start' in _regula(css, '.an-kafelek--pomiar')
    assert 'display: none' in _regula(css, '.an-kafelek--pomiar .an-ogon,\n'
                                           '.an-kafelek--pomiar .an-ogon-wiersz')
    # Nagłówek tabeli zostaje na wierzchu przewijanego ciała — przy samej jego
    # krawędzi: przeglądarka przykleja do krawędzi TREŚCI, więc `top` jest
    # ujemny o górny odstęp ciała (inaczej nad nagłówkiem przesuwał się
    # poprzedni wiersz tabeli).
    naglowek = _regula(css, '.an-kadr-listy--rozwiniety thead th')
    assert 'position: sticky' in naglowek
    odstep = re.search(r'padding: (\d+)px', _regula(css, '.an-karta__cialo')).group(1)
    assert 'top: -%spx' % odstep in naglowek
    # Pierścień obok legendy: `safe center`, inaczej wyśrodkowana, wyższa
    # od ciała legenda wystawałaby POWYŻEJ przewijanego obszaru — tej części
    # nie dałoby się przewinąć.
    pierscien = _regula(css, '.an-karta__cialo--pierscien')
    assert 'align-items: safe center' in pierscien and 'display: flex' in pierscien


def test_szablon_pierscienia_nie_ma_stylu_ukladu_w_atrybucie(strona):
    """Układ ciała karty wykończeń stoi w arkuszu (`safe center`), nie
    w atrybucie `style` — styl w atrybucie przebiłby regułę z arkusza."""
    cialo = re.search(r'<div class="an-karta__cialo an-karta__cialo--pierscien"[^>]*>', strona)
    assert cialo, 'brak ciała karty wykończeń'
    assert 'style=' not in cialo.group(0)


def test_js_mierzy_cialo_zwiniete_i_oddaje_je_do_css(js):
    """Weryfikacja poprawek, znalezisko 3. Wysokość ciała ZWINIĘTEGO zna
    tylko silnik renderujący — to ona ma wejść do wysokości rzędu. analiza.js
    czyta ją RAZ, przed pokazaniem ogona, w trybie pomiaru (klasa na karcie,
    układ robi CSS) i oddaje jako zmienną CSS. Żadnej liczby danych, żadnego
    `style.height` na regionie."""
    assert 'style.maxHeight' not in js
    assert 'style.height' not in js
    rozwin = js.split('function podepnijRozwijanie', 1)[1].split('\n  }\n', 1)[0]
    assert 'offsetHeight' not in rozwin
    pomiar = rozwin.index("zmierzZwinieteCialo(wiersz.closest('.an-karta__cialo'))")
    assert pomiar < rozwin.index('element.hidden = !rozwiniete')
    assert rozwin.index('element.hidden = !rozwiniete') < rozwin.index('odslonOgon(wiersz, elementy[0])')
    zmierz = js.split('function zmierzZwinieteCialo', 1)[1].split('\n  }\n', 1)[0]
    assert zmierz.index("classList.add('an-kafelek--pomiar')") \
        < zmierz.index('getBoundingClientRect().height') \
        < zmierz.index("classList.remove('an-kafelek--pomiar')")
    assert "style.setProperty('--wys-zwinieta'" in zmierz
    # Wiersze ogona tabel (miks, podział lejka) muszą dać się schować
    # w trybie pomiaru — to <tr>, nie pojemnik .an-ogon.
    for funkcja in ('rysujTabeleMiksu', 'rysujPodzialLejka'):
        fragment = js.split('function %s' % funkcja, 1)[1].split('\n  }\n', 1)[0]
        assert "classList.add('an-ogon-wiersz')" in fragment, funkcja
    # Po zmianie szerokości strony ciało zwinięte ma inną wysokość —
    # rozwinięte karty mierzą się od nowa.
    ponownie = js.split('function podepnijPomiarRozwinietych', 1)[1].split('\n  }\n', 1)[0]
    assert 'ResizeObserver' in ponownie and 'zmierzZwinieteCialo(cialo)' in ponownie
    start = js[js.index("addEventListener('DOMContentLoaded'"):]
    assert 'podepnijPomiarRozwinietych()' in start


def test_js_po_rozwinieciu_odslania_ogon_w_obrebie_karty(js):
    """Bez wolnego miejsca ogon ląduje pod dolną krawędzią ciała karty —
    kliknięcie „Pozostałe" nie zmieniałoby na ekranie nic poza paskiem
    przewijania. Ciało przewija się więc tak, żeby wiersz „Pozostałe" stanął
    u góry (pod przyklejonym nagłówkiem tabeli), a pod nim ogon. Przewija się
    WYŁĄCZNIE ciało karty (`scrollTop`), nie strona (`scrollIntoView`)."""
    odslon = js.split('function odslonOgon', 1)[1].split('\n  }\n', 1)[0]
    assert "wiersz.closest('.an-karta__cialo')" in odslon
    assert 'cialo.scrollTop = ' in odslon
    assert 'scrollIntoView' not in odslon
    assert "querySelector('thead')" in odslon


def test_rozwijany_wiersz_nie_uzywa_czerwieni():
    """Czerwien jest zarezerwowana dla bledow (i dla ostrzezenia o saldzie).
    Rozwiniecie listy bledem nie jest."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    blok = css.split('/* ===== ROZWIJANY WIERSZ', 1)[1]
    # Tylko ta sekcja — do nagłówka następnej. Dawniej blok ciągnął się do
    # końca pliku, więc łapał czerwień BŁĘDÓW z sekcji trybu edycji
    # (błąd zapisu w pasku, błąd wczytania kafelka), gdzie jest na miejscu.
    blok = blok.split('/* =====', 1)[0]
    assert '.an-rozwin' in blok, 'sekcja rozwijanego wiersza nie została znaleziona'
    for zakazany in ('--bad', '#B33A2B', 'red'):
        assert zakazany not in blok, 'rozwijany wiersz siega po czerwien: %s' % zakazany


def test_tabele_z_ogonem_maja_kadr_przewijania(strona):
    """Wiersze ogona w tabeli to <tr> i nie da sie ich opakowac we wspolny,
    przewijany blok — wiec przewija sie cala tabela. Kadr musi byc w szablonie,
    bo JavaScript tylko dokłada mu klase na czas rozwiniecia."""
    soup = BeautifulSoup(strona, 'html.parser')
    for klucz in ('mix', 'lejek-podzial'):
        kadr = soup.select_one('[data-kadr="%s"]' % klucz)
        assert kadr is not None, 'brak kadru przewijania dla %s' % klucz
        assert kadr.select_one('table') is not None, klucz


# --- kwoty milionowe mieszcza sie w kartach (ogledziny 23.09.2026) ----------
#
# Przy zakresie „calosc" kwoty milionowe („1 592 080") wystawaly z kolumny
# liczb, ktorej szerokosc nadawal analiza.js (34 px na kartach dostawy
# i wojewodztw): krawedz karty je ucinala, a rozwiniety ogon „Pozostale"
# dostawal poziomy pasek przewijania. Te testy pilnuja ZRODLA — CSS-u, ktory
# gwarantuje miejsce na osiem cyfr. Dowodem, ze na zywej stronie nic sie nie
# ucina, jest pomiar w przegladarce (kazdy wymiar kazdej karty, 1600/1440/1200
# px, liczby podmienione na „99 999 999"); tego pytest bez przegladarki nie
# odtworzy, bo szerokosc tekstu zna dopiero silnik renderujacy.

# Najdluzsza liczba, ktora kazda kolumna liczb ma pomiescic w calosci: osiem
# cyfr w zapisie pl-PL (twarda spacja co trzy cyfry), czyli dziesiec znakow.
NAJDLUZSZA_LICZBA = '99 999 999'
# IBM Plex Mono: kazdy znak (cyfra, spacja, przecinek) ma 600/1000 em.
SZEROKOSC_ZNAKU_MONO_EM = 0.6


def _regula(css, selektor):
    """Tresc reguly o DOKLADNIE tym selektorze (komentarze wyciete).
    Kilka regul z tym samym selektorem — tresc wszystkich, sklejona."""
    bez_komentarzy = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    tresci = re.findall(r'(?:^|[}\n])\s*' + re.escape(selektor) + r'\s*\{([^}]*)\}',
                        bez_komentarzy)
    assert tresci, 'brak reguly %s w analiza.css' % selektor
    return '\n'.join(tresci)


def test_kolumna_liczb_w_wierszu_miesci_osiem_cyfr(js):
    """Kolumna liczb karty ze slupkami ma dolna granice w znakach Mono, nie
    sztywna szerokosc w pikselach za mala na osiem cyfr. `ch` to szerokosc
    cyfry „0" w kroju elementu — w kroju o stalej szerokosci znaku dokladnie
    tyle zajmuje kazdy znak liczby, wiec 10ch to „99 999 999" co do piksela."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    baza = _regula(css, '.an-wiersz__wartosc')
    assert "'IBM Plex Mono'" in baza, 'rachunek w ch dziala tylko w kroju o stalej szerokosci'
    assert 'letter-spacing' not in baza, 'odstep miedzyliterowy rozjechalby rachunek w ch'
    assert 'white-space: nowrap' in baza

    kolumna = _regula(css, '.an-wiersz__wartosc:not(.an-wiersz__wartosc--slaba)')
    granica = re.search(r'min-width:\s*(\d+)ch', kolumna)
    assert granica, 'kolumna liczb nie ma dolnej granicy w znakach'
    assert int(granica.group(1)) >= len(NAJDLUZSZA_LICZBA), \
        'kolumna liczb ma mniej miejsca niz %r' % NAJDLUZSZA_LICZBA
    # Liczba dluzsza niz granica poszerza swoj wiersz, zamiast wylac sie
    # z kolumny: podstawa flex z tresci, nie z `style.width` nadanego w JS.
    assert 'flex-basis: content' in kolumna
    udzial = _regula(css, '.an-wiersz__wartosc--slaba')
    assert 'min-width: max-content' in udzial
    assert 'max-width' not in baza + kolumna + udzial


def test_js_nie_nadpisuje_minimum_kolumny_liczb(js):
    """analiza.js nadaje kolumnie liczb `style.width` — to punkt wyjscia, ktory
    `min-width` z CSS przebija. Styl inline ma jednak pierwszenstwo przed
    arkuszem: `style.minWidth`, `style.maxWidth` albo `flex` wpisane w JS
    przywrocilyby sztywna kolumne po cichu, przy zielonych testach CSS."""
    for zakazane in ('style.minWidth', 'style.maxWidth', 'style.flex'):
        assert zakazane not in js, zakazane
    # Wiersze legendy wykonczen maja styl inline (cssText) — bez szerokosci
    # i bez flex na kwotach, inaczej regula legendy z CSS nie mialaby mocy.
    for linia in re.findall(r"style\.cssText = '([^']*)'", js):
        for zakazane in ('width', 'flex-shrink', 'flex-basis', 'flex:', 'white-space'):
            assert zakazane not in linia, (zakazane, linia)


def test_jednostki_naglowka_stoja_przy_prawej_krawedzi():
    """Kolumna liczb bywa szersza niz szerokosc z JS, wiec jednostka stoi nad
    liczbami tylko dlatego, ze i ona, i liczby sa dosuniete do prawej. Przy
    dwoch jednostkach (lejek: „szt." i „%") samo `space-between` stawialo
    pierwsza w polowie wolnego miejsca — podpis zabiera je wiec w calosci."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    assert 'margin-right: auto' in _regula(css, '.an-naglowek-kolumn > :first-child')
    assert 'text-align: right' in _regula(css, '.an-naglowek-kolumn__jednostka')
    assert 'text-align: right' in _regula(css, '.an-wiersz__wartosc')


def test_nazwa_w_wierszu_ustepuje_przed_liczba():
    """Gdy w wierszu brakuje miejsca, kurczy sie slupek, potem nazwa (z
    wielokropkiem) — nigdy liczba. `flex: none` na nazwie zostawialo ja
    sztywna i przy waskiej karcie wypychalo liczbe poza krawedz."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    nazwa = _regula(css, '.an-wiersz__nazwa')
    assert 'flex: none' not in nazwa
    assert 'min-width: 0' in nazwa
    assert 'text-overflow: ellipsis' in nazwa
    assert 'min-width: 0' in _regula(css, '.an-wiersz__tor')


def test_legenda_wykonczen_nie_wypycha_kwoty():
    """Legenda pierscienia: nazwa bez miejsca na zlamanie („Zachodniopomorskie")
    wypychala kwote poza legende, a rozwiniety ogon dostawal poziomy pasek.
    Kwota nie ustepuje; nazwa schodzi do zera z wielokropkiem, a przy dwoch
    kwotach (segment porownawczy) wiersz sie zawija."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    kwota = _regula(css, '.an-karta__cialo--pierscien [data-lista] .an-mono')
    assert 'flex: none' in kwota and 'white-space: nowrap' in kwota
    wiersz = _regula(css, '.an-karta__cialo--pierscien [data-lista] > div:not(.an-ogon),\n'
                          '.an-karta__cialo--pierscien .an-ogon > div')
    assert 'flex-wrap: wrap' in wiersz
    nazwa = _regula(css, '.an-karta__cialo--pierscien [data-lista] > div:not(.an-ogon)'
                         ' > :not(.an-probka):not(.an-mono),\n'
                         '.an-karta__cialo--pierscien .an-ogon > div > :not(.an-probka):not(.an-mono)')
    for deklaracja in ('min-width: 0', 'overflow: hidden', 'text-overflow: ellipsis'):
        assert deklaracja in nazwa, deklaracja


def test_kolumny_liczb_tabel_waskich_mieszcza_osiem_cyfr():
    """Tabela podzialu lejka i „poza mapa" (table-layout: fixed, liczby
    wyrownane do prawej): kolumna liczb musi pomiescic osiem cyfr Mono
    (11 px) i zostawic odstep od liczby w kolumnie obok — inaczej dwie
    osmiocyfrowe zlewaja sie w jeden ciag albo wchodza na siebie."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    potrzeba = len(NAJDLUZSZA_LICZBA) * SZEROKOSC_ZNAKU_MONO_EM * 11 + 8
    for selektor in ('.an-tabela--waska th:not(:first-child),\n'
                     '.an-tabela--waska td:not(:first-child)',
                     '.an-mapa .an-tabela--waska th:not(:first-child),\n'
                     '.an-mapa .an-tabela--waska td:not(:first-child)'):
        szerokosc = re.search(r'width:\s*(\d+)px', _regula(css, selektor))
        assert szerokosc and int(szerokosc.group(1)) >= potrzeba, \
            '%s: %s px < %s px' % (selektor.split(',')[0], szerokosc and szerokosc.group(1), potrzeba)
    # Czcionka komorek tych tabel to 11 px — na niej stoi rachunek wyzej.
    assert 'font-size: 11px' in _regula(css, '.an-tabela--waska th, .an-tabela--waska td')


def test_tabela_poza_mapa_schodzi_pod_mape_gdy_obok_brak_miejsca():
    """Obok mapy (siatka ponizej 1500 px) przy 1200 px okna zostawalo 146 px
    na kolumny 74 + 104 px: kolumna nazw spadala do zera, a liczby zamowien
    ucinala krawedz karty. Zapytanie o KONTENER (szerokosc karty zalezy tez
    od sidebara) sprowadza tabele pod mape."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    assert '.an-mapa { container: an-mapa / inline-size; }' in css
    blok = css.split('@container an-mapa (max-width: 520px) {', 1)
    assert len(blok) == 2, 'brak zapytania o kontener mapy'
    assert 'grid-column: 1 / -1' in blok[1].split('}', 1)[0]
    # Tylko w ukladzie z siatka (<= 1500 px); powyzej karta jest pionowa.
    assert '@media (max-width: 1500px) {\n  @container an-mapa (max-width: 520px) {' in css


def _liczba_px(tekst, wzor):
    trafienie = re.search(wzor, tekst)
    assert trafienie, wzor
    return float(trafienie.group(1))


# Najmniejszy krój liczby KPI — decyzja z partii E (punkt E7): pięć pól
# w rzędzie jak w makiecie, krój płynny, najmniej ~18 px.
KROJ_MINIMALNY_KPI = 18


def test_kpi_miesci_osiem_cyfr_przy_kazdej_szerokosci_karty():
    """Partia E, punkt E7 (wraca do makiety). Naprawa be4f507 przełączyła KPI
    na układ 3+2 przy każdej szerokości ≤1600 px, żeby „4 527 414" przy
    zakresie „całość" zmieściło się w polu — i pierwszy rząd urósł o 53 px
    także przy bieżącym miesiącu, gdzie liczby są krótkie.

    Decyzja: PIĘĆ pól w rzędzie, krój płynny, zależny od szerokości KARTY
    (zapytanie o kontener, `clamp()` z `cqi`), najmniej 18 px. Układ 3+2
    zostaje tylko wtedy, gdy karta jest tak wąska, że „99 999 999" w 18 px
    się nie mieści. Te same progi liczą się dla 3, 2 i 1 pola."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    assert 'container: an-kpi / inline-size' in _regula(css, '.an-kafelek[data-typ="kpi"]')

    # Metryka kroju — z arkusza, nie przepisana do testu.
    liczba = _regula(css, '.an-liczba')
    assert "'IBM Plex Mono'" in liczba
    krój_bazowy = _liczba_px(liczba, r'font: 700 (\d+)px')
    odstep_liter_em = _liczba_px(liczba, r'letter-spacing: (-?[\d.]+)em')
    em_na_znak = SZEROKOSC_ZNAKU_MONO_EM + odstep_liter_em
    em_liczby = len(NAJDLUZSZA_LICZBA) * em_na_znak
    glowa = _liczba_px(_regula(css, '.an-karta__glowa'), r'padding: \d+px (\d+)px')
    pole = _liczba_px(_regula(css, '.an-kpi__pole'), r'padding: 0 (\d+)px')
    # Linia podziału pola zabiera piksel z jego treści — pierwsza wersja tej
    # poprawki o nim zapomniała i „99 999 999" wystawało o 1 px (1200 i 901 px).
    linia = _liczba_px(_regula(css, '.an-kpi__pole'), r'border-right: (\d+)px')

    kpi_liczba = _regula(css, '.an-kpi .an-liczba')
    assert ('font-size: clamp(%dpx, calc(((100cqi - %dpx) / var(--kpi-kolumny) '
            '- var(--kpi-odstep)) / %s), %dpx)' % (
                KROJ_MINIMALNY_KPI, 2 * glowa, round(em_liczby, 2), krój_bazowy)) in kpi_liczba
    baza = _regula(css, '.an-kpi')
    # Najwęższe pole w rzędzie pięciu: odstęp z obu stron i linia podziału.
    assert '--kpi-kolumny: 5' in baza and '--kpi-odstep: %dpx' % (2 * pole + linia) in baza

    # Układy z arkusza: liczba kolumn, odstęp (padding) najwęższego pola
    # i zakres szerokości karty, w którym obowiązują.
    uklady = {}
    for warunek, tresc in re.findall(r'@container an-kpi \(([^)]*)\) \{(.*?)\n\}', css, re.S):
        kolumny = int(re.search(r'--kpi-kolumny: (\d+)', tresc).group(1))
        dolny = re.search(r'(\d+)px <= width', warunek)
        uklady[kolumny] = {
            'odstep': float(re.search(r'--kpi-odstep: (\d+)px', tresc).group(1)),
            'dolny': float(dolny.group(1)) if dolny else None,
            'gorny': float(re.search(r'width < (\d+)px', warunek).group(1)),
            'tresc': tresc,
        }
    assert sorted(uklady) == [1, 2, 3]
    # Zakresy stykają się bez dziur i bez nakładek: 1 → 2 → 3 → 5 (bazowy).
    assert uklady[1]['dolny'] is None
    assert uklady[1]['gorny'] == uklady[2]['dolny']
    assert uklady[2]['gorny'] == uklady[3]['dolny']
    assert uklady[3]['odstep'] == 2 * pole + linia
    assert uklady[2]['odstep'] == pole + linia
    uklady[5] = {'odstep': 2 * pole + linia, 'dolny': uklady[3]['gorny']}
    for kolumny in (2, 3, 5):
        dolny = uklady[kolumny]['dolny']
        tekst = (dolny - 2 * glowa) / kolumny - uklady[kolumny]['odstep']
        # Przy DOLNYM progu układu „99 999 999" mieści się w polu w kroju
        # minimalnym — i próg jest NAJNIŻSZY, przy którym to prawda (piksel
        # niżej już nie), więc układ z mniejszą liczbą pól nie wchodzi ani
        # piksela za wcześnie. To jest sedno decyzji: 3+2 tylko z konieczności.
        assert em_liczby * KROJ_MINIMALNY_KPI <= tekst + 0.01, (kolumny, dolny)
        o_piksel_nizej = (dolny - 1 - 2 * glowa) / kolumny - uklady[kolumny]['odstep']
        assert em_liczby * KROJ_MINIMALNY_KPI > o_piksel_nizej, (kolumny, dolny)
    # Jedna kolumna: pola bez odstępów i linii podziału.
    assert uklady[1]['odstep'] == 0
    assert '.an-kpi__pole { padding: 0; border-right: 0; }' in uklady[1]['tresc']
    # Siatka pól zmienia się razem z liczbą kolumn, a linie podziału znikają
    # na końcu KAŻDEGO rzędu, nie tylko przy ostatnim polu.
    for kolumny in (2, 3):
        tresc = uklady[kolumny]['tresc']
        assert 'grid-template-columns: repeat(%d, minmax(0, 1fr))' % kolumny in tresc
        assert '.an-kpi__pole:nth-child(%dn) { padding-right: 0; border-right: 0; }' % kolumny in tresc
        assert '.an-kpi__pole:nth-child(%dn + 1) { padding-left: 0; }' % kolumny in tresc


def test_kpi_liczby_stoja_w_jednej_linii_nawet_gdy_podpis_sie_lamie():
    """W kroju 18 px pole ma ~102 px, a „Sprzedaż netto zł" i „Śr. zamówienie
    zł" mają ok. 110 px — podpis łamie się na dwie linie (makieta pozwala).
    Wtedy liczba w TYM polu stała 13 px niżej niż w pozostałych. Pola dzielą
    więc wiersze siatki karty (subgrid): wiersz podpisów ma wysokość
    najwyższego podpisu i wszystkie liczby stoją w jednej linii."""
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    pole = _regula(css, '.an-kpi__pole')
    assert 'grid-template-rows: subgrid' in pole
    assert 'grid-row: span 4' in pole


def test_licznik_popovera_filtra_formatuje_jak_pulpit(js, js_filtra):
    """Kontrola końcowa, DROBNE 5. Licznik zamówień przy wartości w popoverze
    szedł przez gołe `String()`, więc popover pisał „2361", a karta obok
    „2 361". Popover ma własny `fmt0` (ładuje się też bez analiza.js,
    w Eksploratorze i Arkuszu) z tymi samymi opcjami co pulpit."""
    def opcje(zrodlo):
        definicja = zrodlo.split('var fmt0 = new Intl.NumberFormat', 1)[1].split(');', 1)[0]
        return re.sub(r'\s+', '', definicja)

    assert "useGrouping:'always'" in opcje(js_filtra)
    assert opcje(js_filtra) == opcje(js), 'popover formatuje inaczej niż pulpit'
    assert 'String(w.zamowienia)' not in js_filtra
    assert "'an-mono an-filtr-licznik', fmt0.format(w.zamowienia)" in js_filtra


def test_js_filtra_bierze_komunikat_o_ucieciu_z_serwera(js_filtra):
    """Przy porzadku po sprzedazy z listy wypada to, co sprzedaje sie najslabiej;
    przy chronologicznym — NAJSTARSZE daty. Jeden napis wpisany w JavaScripcie
    musialby jednemu z tych przypadkow klamac."""
    assert 'dane.opis_uciecia' in js_filtra
    assert 'Pokazano najważniejsze wartości' not in js_filtra


# --- partia E, punkt E2: koło na karcie „Klienci według" ----------------------

def test_karta_klientow_ma_kolo_pod_naglowkiem_i_legende_pod_kolem(strona):
    """„kafel »Klienci wg.« ma mieć wykres kołowy, pod nim informacje % oraz
    kwotowe". Anatomia karty bez zmian (nagłówek + selektor + treść + jedno
    wyjście), w treści: koło, POD nim legenda-tabela, pod nią „Lead → klient"
    i „Nowi w okresie" oraz uwaga o zasięgu."""
    klucz = KLUCZ['klienci']
    karta = strona.split(f'data-klucz="{klucz}"')[1].split('</section>')[0]
    kolo = karta.index('an-wykres--pierscien')
    legenda = karta.index('<table')
    para = karta.index('Lead → klient')
    uwaga = karta.index(f'data-pole="{klucz}.uwaga"')
    assert kolo < legenda < para < uwaga
    # Ten sam komponent, co pierścień wykończeń: nakładka ze środkiem.
    assert f'data-pole="{klucz}.udzial"' in karta
    assert f'data-pole="{klucz}.nazwa"' in karta
    assert f'data-lista="{klucz}"' in karta
    # Jedno wyjście w stopce.
    assert karta.count('an-karta__stopka') == 1


def test_kilka_kart_klientow_ma_rozne_identyfikatory_kanw(client, app):
    """Każde płótno ma unikalne `id` — przy dwóch kartach „Klienci" z różnymi
    wymiarami dwa elementy o tym samym `id` sprawiłyby, że Chart.js rysuje oba
    koła w pierwszym."""
    client.post('/reports/api/uklad', json={'uklad': [
        {'typ': 'klienci', 'wymiar': 'liczba_zamowien'},
        {'typ': 'klienci', 'wymiar': 'caretaker'}]})
    strona = client.get('/reports/analiza').get_data(as_text=True)
    identyfikatory = re.findall(r'<canvas id="([^"]+)"', strona)
    assert 'an-wykres-klienci-liczba_zamowien' in identyfikatory
    assert 'an-wykres-klienci-caretaker' in identyfikatory
    assert len(identyfikatory) == len(set(identyfikatory))


def test_js_rysuje_kolo_klientow_tym_samym_komponentem_co_wykonczenia(js):
    """Drugi komponent koła oznaczałby dwie konwencje w jednej aplikacji."""
    wykonczenie = js.split('function rysujWykonczenie')[1].split('\n  }\n')[0]
    klienci = js.split('function rysujKoloKlientow')[1].split('\n  }\n')[0]
    assert 'rysujPierscien(' in wykonczenie and 'rysujPierscien(' in klienci
    # Środek pierścienia i udziały przychodzą z serwera — przeglądarka nie
    # szuka największego kawałka i nie dzieli.
    assert 'karta.najwiekszy' in klienci
    assert '/ suma' not in klienci and 'Math.max' not in klienci


# --- partia E, punkt E3: wspólny dymek wykresów --------------------------------
# Cytat prezesa: „tooltipy muszą mieć pełne tło, ponieważ czasami są
# nieczytelne + jeśli wychodzą poza canvas wykresu są ucinane". Domyślny dymek
# Chart.js jest półprzezroczysty, rysuje się NA KANWIE (więc ucina się na jej
# krawędzi) i powtarza etykietę w tytule i w treści.

def test_kazdy_wykres_wylacza_dymek_chartjs_i_bierze_wspolny(js):
    """Wszystkie wykresy pulpitu: `tooltip.enabled = false` i `external`."""
    wykresy = js.count('new Chart(')
    assert wykresy >= 2
    assert js.count('tooltip: opcjeDymka(') == wykresy
    opcje = js.split('function opcjeDymka')[1].split('\n  }\n')[0]
    assert 'enabled: false' in opcje and 'external:' in opcje
    # Żadnego starego dymka na kanwie.
    assert 'callbacks: { label' not in js


def test_dymek_to_jeden_element_w_body_poza_karta_i_pulpitem(strona):
    """W <body>, a nie w karcie (overflow karty by go ucinał) — jeden na stronę."""
    assert strona.count('id="an-dymek"') == 1
    po_main = strona.split('</main>')[1]
    assert 'id="an-dymek"' in po_main
    dymek = strona.split('id="an-dymek"')[0].rsplit('<', 1)[1] + strona.split('id="an-dymek"')[1].split('>')[0]
    assert 'hidden' in dymek and 'role="tooltip"' in dymek


def test_dymek_ma_kryjace_tlo_i_nie_lapie_klikniec():
    css = open(SCIEZKA_CSS, encoding='utf-8').read()
    blok = _regula(css, '.an-dymek')
    assert 'pointer-events: none' in blok
    assert 'position: fixed' in blok
    tlo = re.search(r'background:\s*([^;]+);', blok).group(1)
    assert 'rgba' not in tlo and 'transparent' not in tlo and 'opacity' not in blok
    assert '.an-dymek[hidden] { display: none; }' in css


def test_dymek_jest_dociskany_do_krawedzi_okna_i_znika(js):
    pozycja = js.split('function ustawPozycjeWOknie')[1].split('\n  }\n')[0]
    assert 'window.innerWidth' in pozycja and 'window.innerHeight' in pozycja
    # Znika po przewinięciu, przy niszczeniu wykresu (wymiana kafelka,
    # podgląd, edycja, Anuluj, usunięcie) i po dotknięciu gdzie indziej.
    assert "addEventListener('scroll', schowajDymekWykresu, true)" in js
    zniszcz = js.split('function zniszczWykres')[1].split('\n  }\n')[0]
    assert 'schowajDymekWykresu()' in zniszcz
    # Treść wyłącznie przez textContent / createElement.
    wypelnij = js.split('function wypelnijDymekWykresu')[1].split('\n  }\n')[0]
    assert 'innerHTML' not in wypelnij and 'textContent' in wypelnij


def test_dymek_kola_niesie_udzial_z_payloadu_a_nie_liczy_go(js):
    pierscien = js.split('function rysujPierscien')[1].split('\n  }\n')[0]
    assert 'w.udzial' in pierscien
    assert '/ suma' not in pierscien and 'reduce(' not in pierscien
    # Etykiety miar dymka z serwera, jak jednostki.
    assert 'etykietyMiar' in pierscien


def test_payload_niesie_etykiety_miar_dla_dymka(client):
    dane = client.get('/reports/api/analytics').get_json()
    assert dane['etykiety_miar']['netto'] == 'Netto'
    assert dane['etykiety_miar']['udzial'] == 'Udział'


# --- partia E, punkt E7: drobne domknięcia frontu ----------------------------

def test_legenda_wykonczen_ma_pelna_nazwe_w_podpowiedzi(js):
    """Nazwa ucięta wielokropkiem nie dawała się przeczytać w całości."""
    legenda = js.split('function rysujLegendeWykonczenia')[1].split('\n  }\n')[0]
    assert 'nazwa.title = w.etykieta' in legenda


def test_js_nie_ma_martwej_szerokosci_kolumny_liczb(js):
    """CSS nadpisuje ją od ca9fb27 (min-width: 10ch, flex-basis: content)."""
    assert 'szerokoscWartosci' not in js
    assert 'wartosc.style.width' not in js
    assert "liczba.style.width = '40px'" not in js
