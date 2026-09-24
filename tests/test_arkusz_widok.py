# -*- coding: utf-8 -*-
"""Widok arkusza: trasa, szkielet HTML i arkusz stylow.

Front sprawdzamy STRUKTURALNIE, na zrodle — obraz testowy nie ma node'a,
wiec nic tu nie uruchamia JavaScriptu ani nie renderuje CSS-a. Konwencja
tests/test_checkout_js.py i tests/test_reports_kolory_frontu.py.
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
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import reports_bp
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.users.models import User

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_ARKUSZA = os.path.join(KORZEN, 'modules', 'reports', 'static', 'css', 'arkusz.css')
JS_ARKUSZA = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'arkusz.js')
SZABLON_ARKUSZA = os.path.join(KORZEN, 'modules', 'reports', 'templates',
                               'analiza', 'arkusz.html')

_TABLES = [m.__table__ for m in (User, SalesClient, SalesOrder, SalesOrderItem)]


def zrodlo(sciezka):
    with open(sciezka, encoding='utf-8') as plik:
        return plik.read()


@pytest.fixture()
def klient_http():
    from modules.users.services.permission_service import PermissionService
    oryginal = PermissionService.user_has_module_access
    PermissionService.user_has_module_access = staticmethod(lambda u, m: True)

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(reports_bp)
    app.add_url_rule('/login', 'login', lambda: 'login')
    pulpit = Blueprint('dashboard', __name__)
    pulpit.add_url_rule('/dashboard', 'dashboard', lambda: 'pulpit')
    app.register_blueprint(pulpit)
    app.jinja_loader = ChoiceLoader([
        DictLoader({'sidebar/sidebar.html': '<nav id="sidebar"></nav>',
                    'access_denied.html': '<p>{{ module_name }}</p>'}),
        app.jinja_loader,
    ])
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        db.session.add(User(email='handlowiec@woodpower.pl', password='x',
                            role='user', active=True))
        db.session.add(User(email='szef@woodpower.pl', password='x',
                            role='admin', active=True))
        db.session.commit()
    klient = app.test_client()
    with klient.session_transaction() as sesja:
        sesja['user_email'] = 'szef@woodpower.pl'
    yield klient
    PermissionService.user_has_module_access = oryginal


def html_arkusza(klient, **parametry):
    odpowiedz = klient.get('/reports/arkusz', query_string=parametry)
    assert odpowiedz.status_code == 200
    return odpowiedz.get_data(as_text=True)


# ===== trasa i szkielet ================================================

def test_trasa_arkusza_odpowiada_200(klient_http):
    assert klient_http.get('/reports/arkusz').status_code == 200


def test_zaslepka_z_planu_b_zniknela():
    assert not os.path.exists(os.path.join(
        KORZEN, 'modules', 'reports', 'templates', 'analiza',
        'arkusz_placeholder.html'))


def test_arkusz_nie_laduje_arkusza_stylow_starej_zakladki(klient_http):
    # reports.css ma wlasny :root z bootstrapowym --primary-color: #007bff
    # i importuje Poppinsa regula CSS. Nowa zakladka go nie laduje.
    assert 'css/reports.css' not in html_arkusza(klient_http)


def test_arkusz_laduje_analiza_css_i_arkusz_css(klient_http):
    html = html_arkusza(klient_http)
    # analiza.css wnosi @font-face IBM Plex z lokalnego vendora i palete.
    assert 'css/analiza.css' in html
    assert 'css/arkusz.css' in html


def test_arkusz_nie_ma_sidebara(klient_http):
    # Pelne okno: przy 55 kolumnach kazde 56 px to jedna kolumna wiecej.
    assert 'id="sidebar"' not in html_arkusza(klient_http)


@pytest.mark.parametrize('cdn', ['jsdelivr', 'cdnjs', 'unpkg'])
def test_arkusz_nie_laduje_niczego_z_cdn(klient_http, cdn):
    # Safari ITP blokuje jsdelivr i cdnjs. Arkusz nie ma sidebara, wiec
    # nie ma tu nawet wyjatku na Poppinsa z Google Fonts.
    assert cdn not in html_arkusza(klient_http)


def test_narzedziownik_ma_komplet_kontrolek(klient_http):
    html = html_arkusza(klient_http)
    for identyfikator in ('ark-okno', 'ark-szukaj', 'ark-filtry', 'ark-kolumny',
                          'ark-eksport', 'ark-wiecej', 'ark-odrzuc', 'ark-zapisz',
                          'ark-licznik-zmian', 'ark-stan'):
        assert f'id="{identyfikator}"' in html, identyfikator


def test_narzedziownik_ma_powrot_do_analizy(klient_http):
    html = html_arkusza(klient_http)
    assert '/reports/analiza' in html
    assert '>Analiza<' in html or 'Analiza\n' in html


def test_licznik_kolumn_pokazuje_wybrane_i_wszystkie(klient_http):
    html = html_arkusza(klient_http)
    assert '19/55' in html


def test_wybor_kolumn_z_adresu_zmienia_licznik(klient_http):
    html = html_arkusza(klient_http, kolumny='customer_name,wood_species')
    assert '2/55' in html


def test_legenda_wymienia_cztery_rodzaje_kolumn(klient_http):
    html = html_arkusza(klient_http)
    for napis in ('z BaseLinkera', 'tylko CRM', 'wyliczana', 'z modułu produkcji'):
        assert napis in html, napis


def test_szablon_niesie_adresy_wszystkich_endpointow(klient_http):
    html = html_arkusza(klient_http)
    for adres in ('/reports/api/arkusz/dane', '/reports/api/arkusz/zapisz',
                  '/reports/api/arkusz/pobierz', '/reports/api/arkusz/eksport',
                  '/reports/analiza', '/reports/'):
        assert adres in html, adres


def test_szablon_niesie_pelna_liste_kolumn_do_wyboru(klient_http):
    # Okienko „Kolumny" dostaje liste z szablonu, nie z /api/arkusz/dane —
    # inaczej 55 opisow jechaloby przy kazdym przewinieciu.
    html = html_arkusza(klient_http)
    assert 'data-kolumny-wszystkie=' in html
    assert 'Pochodzenie klienta' in html
    assert 'Zapłacono Łoza' in html


def test_arkusz_uzywa_wspolnego_komponentu_filtra(klient_http):
    # filtr.js to ten sam popover, ktorego uzywa dashboard i Eksplorator.
    # Drugi komponent oznaczalby drugi format filtra i rozjazd adresow.
    html = html_arkusza(klient_http)
    assert 'js/filtr.js' in html
    assert 'data-wymiary-filtra=' in html
    assert '/reports/api/wartosci-wymiaru' in html


def test_okno_dat_pokazuje_etykiete_presetu(klient_http):
    html = html_arkusza(klient_http, **{'okno': 'rok'})
    assert 'Rok 20' in html


def test_przyciski_zapisu_sa_wylaczone_w_stanie_zapisanym(klient_http):
    html = html_arkusza(klient_http)
    odrzuc = re.search(r'<button[^>]*id="ark-odrzuc"[^>]*>', html).group(0)
    zapisz = re.search(r'<button[^>]*id="ark-zapisz"[^>]*>', html).group(0)
    assert 'disabled' in odrzuc
    assert 'disabled' in zapisz
    assert 'Wszystko zapisane' in html


def test_stopka_ma_miejsca_na_sumy(klient_http):
    html = html_arkusza(klient_http)
    for identyfikator in ('ark-stopka-pozycje', 'ark-stopka-zamowienia',
                          'ark-stopka-netto', 'ark-stopka-objetosc'):
        assert f'id="{identyfikator}"' in html, identyfikator


def test_admin_moze_wysylac_a_handlowiec_nie(klient_http):
    assert 'data-moze-wysylac="true"' in html_arkusza(klient_http)
    with klient_http.session_transaction() as sesja:
        sesja['user_email'] = 'handlowiec@woodpower.pl'
    assert 'data-moze-wysylac="false"' in html_arkusza(klient_http)


def test_zly_parametr_w_adresie_nie_jest_bledem_strony(klient_http):
    # Nieaktualna zakladka ma pokazac arkusz za biezacy miesiac, a nie strone
    # bledu. Twarda walidacja zostaje na API, gdzie konsumentem jest kod.
    # Ta sama zasada, co na trasach dashboardu i Eksploratora z Planu B.
    assert klient_http.get('/reports/arkusz',
                           query_string={'okno': 'dekada'}).status_code == 200
    assert klient_http.get('/reports/arkusz',
                           query_string={'od': 'wczoraj'}).status_code == 200
    assert klient_http.get('/reports/arkusz',
                           query_string={'kolumny': 'nie_ma'}).status_code == 200


# ===== arkusz stylow ===================================================

@pytest.mark.parametrize('selektor', [
    '.ark-tabela th.crm::before',   # turkusowy pasek nad naglowkiem
    '.ark-tabela .calc',            # wyliczana: wyciszone tlo i kursywa
    '.ark-tabela .prod',            # z produkcji: bezowe tlo
    '.ark-tabela .ord',             # komorka poziomu zamowienia
])
def test_css_definiuje_cztery_rodzaje_komorek(selektor):
    assert selektor in zrodlo(CSS_ARKUSZA)


def test_css_przykleja_naglowek_i_dwie_pierwsze_kolumny():
    css = zrodlo(CSS_ARKUSZA)
    assert 'position: sticky' in css
    assert '.ark-tabela thead th' in css
    assert '.ark-tabela .zamrozona-1' in css
    assert '.ark-tabela .zamrozona-2' in css


def test_css_wirtualizuje_przewijanie_przez_content_visibility():
    # Jedno tbody na zamowienie + content-visibility: auto. Przegladarka
    # pomija uklad i rysowanie dla zamowien poza ekranem, a rowspan zostaje
    # nietkniety — w odroznieniu od wirtualizacji liczonej w JavaScripcie,
    # ktora musialaby sama odtwarzac scalanie komorek.
    css = zrodlo(CSS_ARKUSZA)
    assert 'content-visibility: auto' in css
    assert 'contain-intrinsic-size' in css


def test_css_uzywa_monospace_na_komorkach_liczbowych():
    css = zrodlo(CSS_ARKUSZA)
    assert "'IBM Plex Mono'" in css
    assert '.ark-tabela .m' in css


def test_css_nie_uzywa_czerwieni_na_niezapisane_zmiany():
    # Bursztyn dla niezapisanych zmian, czerwien WYLACZNIE dla bledow.
    css = zrodlo(CSS_ARKUSZA)
    fragment_zmiany = css[css.index('.ark-brudny'):css.index('.ark-brudny') + 900]
    assert '#FDEDCF' in fragment_zmiany or 'var(--warn-bg)' in fragment_zmiany
    assert '#B33A2B' not in fragment_zmiany
    assert '#C4472F' not in fragment_zmiany


def test_css_zeruje_padding_dashboardu_dla_pelnego_okna():
    # analiza.css nadaje .analiza { padding: 0 22px 28px }. Arkusz jest
    # pelnym oknem i musi to skasowac, inaczej siatka nie dotyka krawedzi.
    assert '.analiza.ark' in zrodlo(CSS_ARKUSZA)


def test_szablon_nie_liczy_niczego_w_jinji():
    # Zadna liczba nie jest liczona poza serwisem. W szablonie nie ma
    # arytmetyki na danych — tylko wstawianie gotowych wartosci.
    szablon = zrodlo(SZABLON_ARKUSZA)
    assert 'sum(' not in szablon
    assert '|length' not in szablon


# ===== poprawki z przegladu Zadania 7 ===================================
# Cztery znaleziska [WAZNE]. Piate (zaslepka 501 pod endpointem, ktorego
# bedzie chcialo uzyc Zadanie 4) jest wylacznie ostrzezeniem dla nastepnego
# wykonawcy (komentarz w routers_analiza.py + brief Zadania 4) — nie ma tu
# odpowiednika kodowego do zlapania testem.

def test_css_monospace_dziala_takze_poza_tabela():
    # Etykieta okna dat (#ark-okno-etykieta), licznik kolumn
    # (#ark-licznik-kolumn) i cztery liczby stopki (#ark-stopka-*) maja
    # klase "m" w szablonie, ale leza POZA .ark-tabela — regula
    # .ark-tabela .m (patrz test_css_uzywa_monospace_na_komorkach_liczbowych)
    # ich nie obejmuje. Makieta Arkusz.dc.html:17 ma regule `.m` bez
    # zadnego prefiksu, wiec dziala wszedzie w obrebie arkusza.
    css = zrodlo(CSS_ARKUSZA)
    assert '.ark .m' in css
    fragment = css[css.index('.ark .m'):css.index('.ark .m') + 200]
    assert "'IBM Plex Mono'" in fragment


@pytest.mark.parametrize('identyfikator', [
    'ark-okno-etykieta', 'ark-licznik-kolumn', 'ark-stopka-pozycje',
    'ark-stopka-zamowienia', 'ark-stopka-netto', 'ark-stopka-objetosc',
])
def test_elementy_poza_tabela_maja_klase_m_w_szablonie(klient_http, identyfikator):
    # Sama regula CSS nie dowodzi niczego, jesli szablon przestanie nadawac
    # klase — ten test wiaze oba konce: element MUSI miec "m" wsrod klas.
    html = html_arkusza(klient_http)
    znacznik = re.search(rf'<[^>]*id="{identyfikator}"[^>]*>', html)
    assert znacznik is not None, identyfikator
    klasy = re.search(r'class="([^"]*)"', znacznik.group(0))
    assert klasy is not None, identyfikator
    assert 'm' in klasy.group(1).split(), identyfikator


def test_licznik_zmian_ma_regule_hidden_w_css():
    # `.ark-licznik { display: inline-flex }` (deklaracja autora) wygrywa
    # z regula UA `[hidden] { display: none }` przez specyficznosc, wiec
    # bez wlasnej reguly [hidden] #ark-licznik-zmian byl WIDOCZNY w stanie
    # zapisanym mimo atrybutu `hidden` w arkusz.html — pusty bursztynowy
    # prostokat, ktorego makieta Arkusz.dc.html nie ma. Ten sam blad byl
    # juz raz zlapany w tym projekcie, patrz analiza.css .an-chip[hidden].
    css = zrodlo(CSS_ARKUSZA)
    assert '.ark-licznik[hidden]' in css
    fragment = css[css.index('.ark-licznik[hidden]'):
                   css.index('.ark-licznik[hidden]') + 60]
    assert 'display: none' in fragment


def test_kazdy_rodzaj_kolumny_ma_selektor_css():
    # arkusz_service.RODZAJE = ('bl', 'crm', 'wyliczana', 'produkcja') —
    # dokladnie te napisy ida do data-kolumny-wszystkie (kolumny_arkusza())
    # i sa najbardziej naturalnym wyborem na klase komorki w Zadaniu 8.
    # 'bl' celowo nie ma wlasnej klasy (brak oznaczenia w makiecie — kolumna
    # z BaseLinkera wyglada neutralnie). 'crm' oznacza sie WYLACZNIE na
    # naglowku (turkusowy pasek `th.crm::before`, bez tla na komorkach —
    # pilnuje test_css_definiuje_cztery_rodzaje_komorek). 'wyliczana' i
    # 'produkcja' MUSZA miec selektor `.ark-tabela .<rodzaj>` na komorkach,
    # inaczej traca oznaczenie po cichu, a legenda dalej wymienia cztery
    # rodzaje.
    from modules.reports.arkusz_service import RODZAJE
    css = zrodlo(CSS_ARKUSZA)
    assert set(RODZAJE) == {'bl', 'crm', 'wyliczana', 'produkcja'}
    assert '.ark-tabela th.crm' in css
    for rodzaj in ('wyliczana', 'produkcja'):
        assert f'.ark-tabela .{rodzaj}' in css, rodzaj


def test_stopka_opisuje_sumy_jako_cale_okno_a_nie_widoczna_strone(klient_http):
    # arkusz_service.dane_arkusza() liczy 'podsumowanie' po CALYM oknie dat
    # (warunki_bazowe + warunki_pozycji(filtr)), a nie po stronicowanej
    # partii zamowien (DOMYSLNY_LIMIT=200) — dowiedzione na serwerze przez
    # tests/test_arkusz_dane.py::test_podsumowanie_liczy_cale_okno_a_nie_strone.
    # Ten test pilnuje, ze widok o tym MOWI: uzytkownik przewijajacy
    # pierwsza strone i czytajacy „Suma netto ..." bez zastrzezenia
    # wzialby ja za sume widocznych wierszy (niezmiennik nr 8 ze
    # „Strategii testow" briefu).
    html = html_arkusza(klient_http)
    stopka = html[html.index('id="ark-stopka-pozycje"'):
                  html.index('id="ark-stopka-podpowiedz"')]
    assert 'całe okno dat' in stopka or 'cały wybrany zakres dat' in stopka


# ===== poprawki z przegladu Zadania 8 ===================================
# Cztery znaleziska. [KRYTYCZNE] (zagniezdzone <tbody>) ma dwie polowki:
# szablon pilnuje tu ponizej, JS pilnuje tests/test_arkusz_js.py. Pozostale
# trzy sa [WAZNE].

def test_id_ark_cialo_siedzi_na_tabeli_nie_na_tbody(klient_http):
    # KRYTYCZNE: wstawTbody (arkusz.js) dopina <tbody class="ark-zamowienie">
    # do elementu #ark-cialo. Jesli ten element to <tbody>, kolejne bloki
    # ZAGNIEZDZAJA SIE w nim — przegladarka owija wewnetrzne row-groups
    # w anonimowa tabele i naglowek z danymi dostaja DWIE NIEZALEZNE siatki
    # kolumn (zmierzone w Chromium: 19 kolumn, th != td co do px). Element
    # o id="ark-cialo" MUSI byc <table>, zeby wstawione <tbody> byly jej
    # bezposrednimi dziecmi, tak jak <thead>.
    html = html_arkusza(klient_http)
    znacznik = re.search(r'<[a-z]+[^>]*\bid="ark-cialo"[^>]*>', html)
    assert znacznik is not None
    assert znacznik.group(0).startswith('<table'), znacznik.group(0)
    # Statyczny <tbody> bez dzieci nie ma juz czego robic w szkielecie —
    # dane wstawia wylacznie JS, po jednym <tbody> na zamowienie.
    assert '<tbody id="ark-cialo">' not in html
    # Pusty <tbody> BEZ id bylby dokladnie ta sama pulapka (anonimowy
    # placeholder, ktory JS dopinalby WEWNATRZ niego). Pusty <tbody>
    # Z id-em to co innego: nazwany cel, ktory JS wypelnia po fakcie
    # (np. #ark-dialog-lista w dialogu potwierdzenia, Zadanie 12) —
    # to legalny wzorzec, nie regresja tego bledu.
    #
    # WAZNE, przeglad Zadania 12: wyjatek MUSI byc zawezony do tego
    # KONKRETNEGO, znanego id (ark-dialog-lista), nie do "id w ogole".
    # Szerszy wyjatek zwalnialby z ochrony KAZDY pusty <tbody id="cokolwiek">
    # na stronie — takze wewnatrz glownej siatki #ark-cialo, gdzie oryginalny
    # blad (Zadanie 8, zagniezdzone <tbody>) naprawde zyl.
    assert re.search(r'<tbody(?![^>]*\bid="ark-dialog-lista")[^>]*>\s*</tbody>', html) is None


def test_css_definiuje_stala_szerokosc_kolumn_przez_table_layout_fixed():
    # WAZNE: bez table-layout: fixed deklaracje th[data-typ]/th[data-kolumna]
    # ponizej sa tylko SUGESTIA — przegladarka liczy szerokosc kolumny
    # z tresci najszerszej komorki (auto-layout), wiec ten sam zestaw
    # kolumn ma inna szerokosc dla kazdego okna dat, a przy doczytywaniu
    # kolejnych 200 zamowien kolumny dryga pod reka uzytkownika.
    css = zrodlo(CSS_ARKUSZA)
    poczatek = css.index('.ark-tabela {')
    regula = css[poczatek:css.index('}', poczatek)]
    assert 'table-layout: fixed' in regula
    # Szerokosci sa juz zdefiniowane na th (Zadanie 7) — fixed-layout
    # bierze je z pierwszego wiersza, wiec <colgroup> nie jest potrzebny.
    assert 'th[data-typ="data"]' in css
    assert 'th[data-typ="tekst"]' in css


def test_css_kreskowanie_zablokowanej_komorki_ma_important():
    # WAZNE: `.ark-tabela .ord { background: #FBFAF7 !important }` to skrot
    # "background", ktory bez jawnej wartosci resetuje background-image do
    # "none !important" na kazdej komorce poziomu zamowienia — czyli na
    # wiekszosci komorek, ktore widz uzytkownik bez uprawnien do wysylki
    # do BL (rola "user"). Bez wlasnego !important tutaj kreskowanie
    # znikaloby wlasnie tam: zostaje sam title/aria-label, bez oznaczenia
    # widocznego golym okiem (wymog briefu Zadania 8).
    css = zrodlo(CSS_ARKUSZA)
    poczatek = css.index('.ark-tabela td.zablokowana {')
    regula = css[poczatek:css.index('}', poczatek) + 1]
    assert 'background-image' in regula
    assert 'repeating-linear-gradient' in regula
    # Samo "!important" gdziekolwiek w regule by nie wystarczylo — musi
    # stac PRZY background-image, bo to ta wlasnosc koliduje z .ord.
    fragment_wlasciwosci = regula[regula.index('background-image'):
                                  regula.index(';', regula.index('background-image')) + 1]
    assert '!important' in fragment_wlasciwosci


# ===== fala poprawek „arkusz-front" (Plan C, blok 4) ====================
# Piec znalezisk z przegladu zadan 7+8: dwa [WAZNE] o zrodle prawdy (jednostka
# i lista kolumn), jedno [KRYTYCZNE] o kontrakcie DOM juz zamkniete wczesniej
# (test ponizej tylko spina oba konce), jedno [WAZNE] o pozycji drugiej
# zamrozonej kolumny i jedno [WAZNE] o wyrownaniu numeru BaseLinkera.

def test_stopka_bierze_jednostki_z_rejestru_a_nie_na_sztywno(klient_http, monkeypatch):
    # [WAZNE] nr 1: "zł"/"m³" w stopce byly wpisane na sztywno w arkusz.html,
    # mimo ze rejestr (POLA['order_amount_net'/'total_m3'].jednostka) juz je
    # niesie — dokladnie ta sama zasada (commit a892ca8), ktorej pilnuja inne
    # testy w projekcie. Dowod, ze wartosc NAPRAWDE przychodzi z rejestru,
    # a nie jest tylko przypadkowo taka sama: podmieniamy jednostke w rejestrze
    # i sprawdzamy, ze zmienia sie tez wyrenderowany HTML — hardkodowany napis
    # by tego nie zauwazyl.
    from dataclasses import replace
    from modules.reports.fields import POLA
    monkeypatch.setitem(POLA, 'order_amount_net',
                         replace(POLA['order_amount_net'], jednostka='PLN-TEST'))
    monkeypatch.setitem(POLA, 'total_m3',
                         replace(POLA['total_m3'], jednostka='m3-TEST'))
    html = html_arkusza(klient_http)
    assert 'PLN-TEST' in html
    assert 'm3-TEST' in html
    assert '</b> zł</span>' not in html
    assert '</b> m³</span>' not in html


def test_kolumny_arkusza_lista_nie_niesie_pelnego_opisu():
    # [WAZNE] nr 2: `kolumny_arkusza()` (widok „wszystkich 55") niesie
    # WYLACZNIE to, czego uzywa selektor kolumn w JS (nazwa, etykieta) i
    # istniejace testy tego pliku (rodzaj, metoda_api, edytowalne). Pelny
    # pietnastopolowy opis — z lista statusow BL wlacznie — dostaje wylacznie
    # `kolumna_arkusza(nazwa)`, per faktycznie renderowana kolumna.
    from modules.reports.arkusz_service import kolumny_arkusza
    for kolumna in kolumny_arkusza():
        assert set(kolumna) == {'nazwa', 'etykieta', 'rodzaj', 'metoda_api', 'edytowalne'}, kolumna['nazwa']


def test_data_kolumny_wszystkie_nie_wazy_juz_polowy_strony(klient_http):
    # [WAZNE] nr 2: atrybut wazyl ~27 368 znakow po escapowaniu Jinjy
    # (~77% calej strony) — pelny opis wszystkich 55 kolumn, w tym 18-
    # elementowa lista statusow BL POWIELONA (a w praktyce: obecna choc
    # niepotrzebnie) przy kolumnie 'current_status'. Nazwa statusu nie ma
    # tu juz prawa sie pojawic ani razu — pelny opis, z opcjami wyboru
    # wlacznie, dostaje wylacznie /api/arkusz/dane, dla kolumn faktycznie
    # pokazywanych.
    html = html_arkusza(klient_http)
    poczatek = html.index("data-kolumny-wszystkie='") + len("data-kolumny-wszystkie='")
    koniec = html.index("'", poczatek)
    wartosc = html[poczatek:koniec]
    # Bylo ~27 368 (po escapowaniu Jinjy); skrocony opis daje ~10 100 —
    # spory zapas ponizej progu na wypadek drobnych zmian etykiet w rejestrze.
    assert len(wartosc) < 15000, len(wartosc)
    assert 'opłacone' not in wartosc
    assert 'Pochodzenie klienta' in wartosc  # etykieta zostaje — to jej jedyny konsument


def test_kontrakt_ark_cialo_tabela_i_wstawtbody_sa_zgodne(klient_http):
    # [KRYTYCZNE] (Zadanie 7 vs 8): szablon trzyma teraz id="ark-cialo" na
    # <table>, a JS traktuje je jako BEZPOSREDNIEGO rodzica wstawianych
    # <tbody> (wstawTbody(cialo, ...) → rodzic.appendChild(blok)). Rozjazd
    # (np. gdyby ktos wrocil do <tbody id="ark-cialo">) zagniezdzalby kolejne
    # bloki wewnatrz niego, dajac dwie NIEZALEZNE siatki kolumn. Ten test
    # spina oba konce kontraktu naraz — polowka czysto-JS jest osobno
    # w tests/test_arkusz_js.py.
    html = html_arkusza(klient_http)
    znacznik = re.search(r'<[a-z]+[^>]*\bid="ark-cialo"[^>]*>', html)
    assert znacznik is not None
    assert znacznik.group(0).startswith('<table'), znacznik.group(0)
    js = zrodlo(JS_ARKUSZA)
    assert "getElementById('ark-cialo')" in js
    assert 'wstawTbody(cialo,' in js


def test_css_ark_tabela_ma_jawna_szerokosc_dla_table_layout_fixed():
    # [WAZNE] nr 4: bez jawnej szerokosci na `.ark-tabela` samo
    # `table-layout: fixed` nie gwarantuje nic — silnik i tak dolicza sie
    # WLASNEJ szerokosci tabeli z tresci komorek (m.in. `white-space: nowrap`
    # na najdluzszym kliencie), wiec kazda kolumna renderuje sie inna
    # szerokoscia niz ta zadeklarowana nizej w `th[data-typ]`/`th[data-kolumna]`
    # (zmierzone w przegladarce: „Data" 78px zamiast zadeklarowanych 92px).
    # Druga zamrozona kolumna liczy swoje przesuniecie z FAKTYCZNEJ szerokosci
    # pierwszej (arkusz.js, zamrozDrugaKolumne) — gdy ta szerokosc jest
    # niestabilna (np. zmienia sie po doladowaniu fontow IBM Plex,
    # `font-display: swap` w analiza.css), druga kolumna zostaje na starej,
    # juz nieaktualnej pozycji. Jawna szerokosc odcina tabele od tresci.
    css = zrodlo(CSS_ARKUSZA)
    poczatek = css.index('.ark-tabela {')
    regula = css[poczatek:css.index('}', poczatek)]
    assert 'table-layout: fixed' in regula
    assert 'width:' in regula
    assert 'width: auto' not in regula


def test_service_nr_baselinkera_dostaje_monospace_ale_nie_liczbowa():
    # [WAZNE] nr 5: „Nr BaseLinker" to identyfikator (same cyfry), nie
    # wielkosc liczbowa — nie sumuje sie go i nie porownuje wzrokowo kolumna
    # w kolumne, wiec 'liczbowa' zostaje False (bez wyrownania do prawej,
    # bez separatora tysiecy). Mimo to makieta pokazuje go czcionka
    # monospace ('m' bez 'num'), stad osobna flaga.
    from modules.reports.arkusz_service import kolumna_arkusza
    opis = kolumna_arkusza('baselinker_order_id')
    assert opis['monospace'] is True
    assert opis['liczbowa'] is False
    assert opis['typ'] == 'tekst'


# ===== dialog potwierdzenia (Zadanie 12) ================================

def test_szablon_ma_szkielet_dialogu_potwierdzenia(klient_http):
    html = html_arkusza(klient_http)
    for identyfikator in ('ark-dialog', 'ark-dialog-lista', 'ark-dialog-crm',
                          'ark-dialog-ostrzezenie', 'ark-dialog-niepytaj',
                          'ark-dialog-anuluj', 'ark-dialog-wyslij'):
        assert f'id="{identyfikator}"' in html, identyfikator


def test_dialog_ma_piec_kolumn_z_makiety(klient_http):
    html = html_arkusza(klient_http)
    for naglowek in ('Zamówienie', 'Pole', 'Było', 'Będzie', 'Metoda API'):
        assert f'>{naglowek}<' in html, naglowek
    assert 'Te zmiany zostaną wysłane do BaseLinkera' in html
    assert 'Zostaje tylko w CRM — bez wysyłki' in html


# ===== poprawki z przegladu Zadania 12 ==================================

def test_regresja_pustego_tbody_z_innym_id_jest_lapana():
    # [WAZNE]: wyjatek od reguly „pusty <tbody> to regresja Zadania 8" byl
    # zawezony tylko do „bez atrybutu id w ogole" — czyli DOWOLNY pusty
    # <tbody id="cokolwiek"> (takze wewnatrz glownej siatki #ark-cialo,
    # gdzie oryginalny blad naprawde zyl) przechodzil test bez ostrzezenia.
    # Test dowodzi na samym wzorcu (uzywanym tez wyzej w tym pliku), ze po
    # zawezeniu do KONKRETNEGO id="ark-dialog-lista" regresja z INNYM id
    # (albo bez id wcale) jest zlapana, a jedyny legalny przypadek — nie.
    wzorzec = r'<tbody(?![^>]*\bid="ark-dialog-lista")[^>]*>\s*</tbody>'
    assert re.search(wzorzec, '<tbody id="ark-cialo"></tbody>') is not None
    assert re.search(wzorzec, '<tbody id="ark-jakis-inny-id"></tbody>') is not None
    assert re.search(wzorzec, '<tbody></tbody>') is not None
    assert re.search(wzorzec, '<tbody id="ark-dialog-lista"></tbody>') is None


def test_css_dialog_crm_wiersz_przekresla_wartosc_bylo(klient_http):
    # [WAZNE]: pudelko „Zostaje tylko w CRM" nie odrozniało wizualnie „bylo"
    # od „bedzie" — .ark-tabela .was dziala WYLACZNIE wewnatrz .ark-tabela,
    # a dialog to .ark-dialog__crm-wiersz, wiec renderowal sie bez
    # przekreslenia i bez wyciszonego koloru.
    css = zrodlo(CSS_ARKUSZA)
    assert '.ark-dialog__crm-wiersz .was' in css
    poczatek = css.index('.ark-dialog__crm-wiersz .was')
    regula = css[poczatek:css.index('}', poczatek) + 1]
    assert 'text-decoration: line-through' in regula
    assert '#7F98A0' in regula


def test_css_dialog_crm_wiersz_ma_stale_szerokosci_pierwszych_kolumn():
    # [WAZNE]: bez stalych szerokosci (makieta: 74px / 120px, flex: none)
    # numer zamowienia i etykieta pola miały szerokosc tresci, wiec przy
    # kilku zmianach wiersze w pudelku „Zostaje tylko w CRM" nie zgrywaly
    # sie w kolumny.
    css = zrodlo(CSS_ARKUSZA)
    assert '.ark-dialog__crm-wiersz span:nth-child(1)' in css
    assert '.ark-dialog__crm-wiersz span:nth-child(2)' in css
    poczatek = css.index('.ark-dialog__crm-wiersz span:nth-child(1)')
    fragment = css[poczatek:poczatek + 300]
    assert 'width: 74px' in fragment
    assert 'width: 120px' in fragment
    assert 'flex: none' in fragment


def test_js_numer_zamowienia_w_dialogu_crm_dostaje_klase_m():
    # [WAZNE]: numer zamowienia w pudelku „Zostaje tylko w CRM" renderowal
    # sie IBM Plex Sans zamiast IBM Plex Mono — makieta ma tu class="m",
    # jak kazda inna cyfra w arkuszu.
    js = zrodlo(JS_ARKUSZA)
    poczatek = js.index('function pokazDialog')
    koniec = js.index('function zamknijDialog')
    fragment = js[poczatek:koniec]
    assert "pole.className = 'm'" in fragment


# ===== poprawki z przegladu Zadania 15 ===================================

def test_css_szukajka_moze_sie_skurczyc_zamiast_ucinac_pasek():
    # [WAZNE]: dwa przyciski Zadania 15 („Eksport" 88px + „⋯" 34px) doszly
    # do .ark-narzedziownik, ktory jest display:flex bez flex-wrap, a kazdy
    # jego element ma domyslnie flex: none (sztywna szerokosc). Zmierzone
    # w przegladzie: intrinsic szerokosc paska w stanie czystym wzrosla
    # z ~1038px do ~1184px — a przy overflow:hidden na body (arkusz.css:12)
    # strona nie ma paska przewijania, wiec prawy koniec paska (Odrzuc/
    # Zapisz) jest nieosiagalny na ekranach 1024-1152px. Fix: .ark-szukajka
    # jest jedynym elementem narzedziownika, ktory smie sie skurczyc.
    css = zrodlo(CSS_ARKUSZA)
    regula_szukajki = re.search(r'\.ark-szukajka\s*\{([^}]*)\}', css)
    assert regula_szukajki is not None
    assert 'flex:' in regula_szukajki.group(1)
    assert 'min-width: 0' in regula_szukajki.group(1)


def test_css_szukajka_input_nie_ma_juz_sztywnej_szerokosci():
    # Uzupelnienie powyzszego: samo skurczenie kontenera nic nie da, dopoki
    # <input> w srodku ma zaszyte `width: 190px` — musi rosnac/kurczyc sie
    # razem z rodzicem.
    css = zrodlo(CSS_ARKUSZA)
    regula_inputu = re.search(r'\.ark-szukajka input\s*\{([^}]*)\}', css)
    assert regula_inputu is not None
    assert 'width: 190px' not in regula_inputu.group(1)
    assert 'width: 100%' in regula_inputu.group(1)


# ===== poprawki z przegladu fali 3 (arkusz i eksport) ====================

def test_ark_filtry_ma_ciasnego_pozycjonowanego_rodzica_dla_popovera(klient_http):
    # WAZNE nr 4: filtr.js dopina popover „an-filtr-popover" jako DZIECKO
    # RODZICA kotwicy (`kotwica.parentNode.appendChild(okno)`, filtr.js) i
    # pozycjonuje go „position: absolute; left: 0; top: 34px" WZGLEDEM
    # NAJBLIZSZEGO POZYCJONOWANEGO PRZODKA (analiza.css: „kazda kotwica musi
    # siedziec w elemencie z position: relative"). Bez wlasnego, CIASNEGO
    # opakowania #ark-filtry dziedziczyl pozycjonowanie po CALYM
    # .ark-narzedziownik (position: relative na calym pasku, arkusz.css) —
    # popover wyskakiwalby spod lewej krawedzi paska („Analiza"), nie spod
    # przycisku „Filtry". Dokladnie ta sama klasa bledu, ktora juz raz
    # zablokowala cala zakladke (brakujacy pozycjonowany przodek).
    # Dwie inne kotwice tego samego komponentu (dashboard: .an-kotwica-filtra,
    # Eksplorator: .eks-kotwica-filtra) maja taki wrapper — #ark-filtry
    # reuzywa tej samej, juz zaladowanej klasy (analiza.css), zamiast
    # dublowac regule trzeci raz.
    html = html_arkusza(klient_http)
    dopasowanie = re.search(
        r'<span class="an-kotwica-filtra">\s*<button[^>]*\bid="ark-filtry"', html)
    assert dopasowanie is not None


def test_css_menu_kolumny_nie_rozlewa_sie_poziomo_poza_szerokosc_menu():
    # WAZNE nr 5: `.ark-menu--kolumny` mial `column-count: 2` w polaczeniu
    # z `.ark-menu { max-height: 60vh; overflow: auto }`. Specyfikacja CSS
    # Multi-column NIE gwarantuje, ze tresc zmiesci sie w zadanej liczbie
    # kolumn przy ograniczonej wysokosci — gdy nie miesci sie (55 checkboksow
    # w dwoch kolumnach o wysokosci 60vh), przegladarka dostawia KOLEJNE
    # kolumny W POZIOMIE zamiast przewijac PIONOWO, wiec lista rozlewala sie
    # poza szerokosc rozwijanego menu. CSS Grid nie ma tej wlasciwosci:
    # liczba kolumn jest stala (2), nadmiar tresci przewija sie pionowo
    # w .ark-menu, tak jak wszedzie indziej w tym menu.
    css = zrodlo(CSS_ARKUSZA)
    poczatek = css.index('.ark-menu--kolumny')
    regula = css[poczatek:css.index('}', poczatek) + 1]
    assert 'column-count' not in regula
    assert 'display: grid' in regula
    assert 'grid-template-columns' in regula


# ===== podglad potwierdzenia z serwera (fala 4) =========================
# Dialog przestaje sklada sie WYLACZNIE z zaznaczonych komorek (spec 5.3
# pkt 1) — nowy endpoint POST /api/arkusz/potwierdzenie przepuszcza „zmiany"
# przez arkusz_zapis.pozycje_potwierdzenia (juz przetestowana osobno w
# tests/test_arkusz_zapis.py) i oddaje gotowa liste. Testy ponizej sprawdzaja
# WYLACZNIE endpoint: bramke uprawnien, ksztalt JSON, brak efektow ubocznych.

def _zamowienie_testowe(klient_http, **nadpisania):
    """Jedno zamowienie w bazie testowej `klient_http`. Ten sam minimalny
    ksztalt, co fixture `dane` w tests/test_arkusz_zapis.py — endpoint
    zapisu i endpoint potwierdzenia licza z tych samych kolumn."""
    pola = dict(baselinker_order_id=50854536, date_created=date(2026, 9, 18),
               customer_name='Jan Przykładowy', delivery_state='śląskie',
               client_origin='Sklep', paid_cash=Decimal('0.00'),
               price_type='brutto', paid_amount=Decimal('0.00'),
               balance_due=Decimal('0.00'), own_transport=False, picked_up=False)
    pola.update(nadpisania)
    with klient_http.application.app_context():
        zamowienie = SalesOrder(**pola)
        db.session.add(zamowienie)
        db.session.commit()
        return zamowienie.id


def test_endpoint_potwierdzenia_odpowiada_200_z_lista_pozycji(klient_http):
    id_zam = _zamowienie_testowe(klient_http)
    odpowiedz = klient_http.post('/reports/api/arkusz/potwierdzenie', json={'zmiany': [
        {'poziom': 'zamowienie', 'id': id_zam, 'nazwa': 'delivery_state',
         'jest': 'mazowieckie', 'bylo': 'śląskie'}]})
    assert odpowiedz.status_code == 200
    assert odpowiedz.get_json()['pozycje'] == [{
        'klucz': 'zamowienie:{}:delivery_state'.format(id_zam),
        'zamowienie': 50854536, 'nazwa': 'delivery_state',
        'etykieta': 'Województwo', 'bylo': 'śląskie', 'bedzie': 'mazowieckie',
        'metoda': 'setOrderFields', 'dorozumiane': False,
    }]


def test_endpoint_potwierdzenia_dopisuje_pole_dorozumiane(klient_http):
    # Ten sam przypadek, ktory uzasadnia caly ten endpoint (spec 5.3 pkt 1):
    # edycja SAMEJ kwoty wplaty na zamowieniu z pustym payment_date dolacza
    # date platnosci, ktorej nikt nie edytowal — setOrderPayment podmienia
    # cala platnosc naraz.
    id_zam = _zamowienie_testowe(klient_http)
    odpowiedz = klient_http.post('/reports/api/arkusz/potwierdzenie', json={'zmiany': [
        {'poziom': 'zamowienie', 'id': id_zam, 'nazwa': 'paid_amount',
         'jest': '1000.00', 'bylo': '0.00'}]})
    assert odpowiedz.status_code == 200
    pozycje = odpowiedz.get_json()['pozycje']
    dorozumiane = [p for p in pozycje if p['nazwa'] == 'payment_date']
    assert len(dorozumiane) == 1
    assert dorozumiane[0]['dorozumiane'] is True
    # Pole dorozumiane nie odpowiada zadnej edytowanej komorce — nie ma
    # czego podswietlac po zapisie (patrz docstring pozycje_potwierdzenia).
    assert dorozumiane[0]['klucz'] is None


def test_endpoint_potwierdzenia_ma_te_sama_bramke_uprawnien_co_zapis(klient_http):
    odpowiedz = klient_http.post('/reports/api/arkusz/potwierdzenie', json={'zmiany': []})
    assert odpowiedz.status_code == 400  # dotarl do walidacji — bramka go wpuscila
    with klient_http.session_transaction() as sesja:
        sesja.clear()
    odpowiedz = klient_http.post('/reports/api/arkusz/potwierdzenie', json={'zmiany': []})
    assert odpowiedz.status_code == 401
    assert odpowiedz.get_json() == {'error': 'unauthorized'}


def test_endpoint_potwierdzenia_zwraca_400_z_komunikatem_po_polsku(klient_http):
    odpowiedz = klient_http.post('/reports/api/arkusz/potwierdzenie', json={'zmiany': []})
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zle_zmiany'
    assert odpowiedz.get_json()['komunikat']


def test_endpoint_potwierdzenia_bez_ciala_zwraca_400_a_nie_500(klient_http):
    odpowiedz = klient_http.post('/reports/api/arkusz/potwierdzenie',
                                 data='', content_type='application/json')
    assert odpowiedz.status_code == 400


def test_endpoint_potwierdzenia_nie_odpowiada_na_get(klient_http):
    # Musi byc osobne wywolanie od zapisu (POST /api/arkusz/zapisz) — dialog
    # pokazuje sie PRZED zapisem, GET tu nie ma sensu.
    assert klient_http.get('/reports/api/arkusz/potwierdzenie').status_code == 405


def test_endpoint_potwierdzenia_nie_zapisuje_niczego(klient_http):
    # To WYLACZNIE podglad — zero efektow ubocznych, w odroznieniu od
    # /api/arkusz/zapisz. Regresja tutaj oznaczalaby, ze samo OTWARCIE
    # dialogu potwierdzenia zmienia dane w bazie.
    id_zam = _zamowienie_testowe(klient_http)
    klient_http.post('/reports/api/arkusz/potwierdzenie', json={'zmiany': [
        {'poziom': 'zamowienie', 'id': id_zam, 'nazwa': 'delivery_state',
         'jest': 'mazowieckie', 'bylo': 'śląskie'}]})
    with klient_http.application.app_context():
        assert SalesOrder.query.get(id_zam).delivery_state == 'śląskie'


# ===== ZAMÓWIENIA POZA SPRZEDAŻĄ (partia E, punkt E5) ====================

def test_stopka_mowi_wprost_ze_nie_sumuje_anulowanych_i_nieoplaconych(klient_http):
    """Siatka pokazuje zamówienia anulowane i nieopłacone (wyszarzone), a
    stopka ich nie sumuje — tak jak pulpit. Bez podpisu użytkownik dodałby
    w głowie wyszarzone wiersze do sumy i uznał stopkę za błędną."""
    from modules.reports.service import OPIS_POZA_SPRZEDAZA
    html = html_arkusza(klient_http)
    stopka = html[html.index('id="ark-stopka-pozycje"'):
                  html.index('id="ark-stopka-podpowiedz"')]
    assert OPIS_POZA_SPRZEDAZA in stopka
    assert OPIS_POZA_SPRZEDAZA == 'bez anulowanych i nieopłaconych'


def test_css_wyszarza_zamowienie_poza_sprzedaza_bez_czerwieni_i_bursztynu():
    css = zrodlo(CSS_ARKUSZA)
    poczatek = css.index('tbody.poza-sprzedaza')
    blok = css[poczatek:css.index('/* ===== STOPKA')]
    assert '.ark-wiersz-statusu' in blok
    # Czerwień jest dla błędów, bursztyn dla niezapisanych zmian.
    for zakazany in ('--bad', '--warn', '#C4472F', '#FDECE8', '#FEF4E2', '#D98A16'):
        assert zakazany not in blok, zakazany
    # Stan edycji i wynik zapisu wygrywają z szarością.
    assert ':not(.edytowana)' in blok
    assert ':not(.odrzucona)' in blok
