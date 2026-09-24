# -*- coding: utf-8 -*-
"""Widok Eksploratora: pasek parametrow, panel miar, panel przestawienia.

Eksplorator nie ma sidebara, wiec nie potrzebuje zaslepki Jinja — rejestrujemy
sam blueprint reports na minimalnym Flasku.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import reports_bp
from modules.reports.analiza_service import ETYKIETY_MIAR, MIARY_PANELU, MIARY_PRZESTAWIENIA
from modules.reports.fields import wymiary
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.users.models import User
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów
from modules.quotes.models import QuoteStatus

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCIEZKA_JS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'eksplorator.js')

_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    SalesClient, SalesOrder, SalesOrderItem,
)]


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
    odpowiedz = client.get('/reports/eksplorator?wymiar=order_source'
                           '&przestawienie=miesiac&miara=netto')
    assert odpowiedz.status_code == 200
    return odpowiedz.get_data(as_text=True)


@pytest.fixture()
def js():
    return open(SCIEZKA_JS, encoding='utf-8').read()


# --- strona -----------------------------------------------------------------

def test_trasa_odpowiada_bez_parametrow(client):
    assert client.get('/reports/eksplorator').status_code == 200


def test_sciezka_powrotu_prowadzi_do_analizy(strona):
    assert 'Analiza sprzedażowa' in strona
    assert 'Eksplorator' in strona
    assert 'href="/reports/analiza"' in strona


def test_pasek_parametrow_ma_piec_kontrolek(strona):
    for identyfikator in ('eks-wymiar', 'eks-przestawienie-wybor', 'eks-miara',
                          'eks-zakres', 'eks-filtr'):
        assert f'id="{identyfikator}"' in strona


def test_selektor_wymiaru_ma_wszystkie_wymiary_rejestru(strona):
    for nazwa in wymiary():
        assert f'value="{nazwa}"' in strona


def test_selektor_przestawienia_ma_miesiac_i_wymiary(strona):
    assert 'value="miesiac"' in strona
    assert re.search(r'id="eks-przestawienie-wybor"', strona)


def test_selektor_miary_ma_tylko_miary_addytywne(strona):
    fragment = strona.split('id="eks-miara"')[1].split('</select>')[0]
    for miara in MIARY_PRZESTAWIENIA:
        assert f'value="{miara}"' in fragment
    assert 'value="udzial"' not in fragment
    assert 'value="srednie_zamowienie"' not in fragment


def test_parametry_z_adresu_sa_zaznaczone(client):
    strona = client.get('/reports/eksplorator?wymiar=caretaker'
                        '&przestawienie=wood_species&miara=objetosc').get_data(as_text=True)
    assert re.search(r'value="caretaker"\s+selected', strona)
    assert re.search(r'value="wood_species"\s+selected', strona)
    assert re.search(r'value="objetosc"\s+selected', strona)


def test_sa_dwa_panele_z_naglowkami_z_makiety(strona):
    assert 'id="eks-miary"' in strona
    assert 'id="eks-przestawienie"' in strona
    assert 'wszystkie miary' in strona
    assert 'Przestawienie włączone' in strona


def test_panel_miar_ma_osiem_naglowkow_kolumn(strona):
    for miara in MIARY_PANELU:
        assert ETYKIETY_MIAR[miara] in strona


def test_panel_przestawienia_ma_kolumny_trend_i_zmiana(strona):
    assert '>Trend<' in strona
    assert '>Zmiana<' in strona


def test_strona_oglasza_ladowanie(strona):
    assert 'aria-busy="true"' in strona
    assert 'class="sk' in strona


def test_strona_nie_siega_do_cdn(strona):
    for zakazane in ('fonts.googleapis.com', 'cdn.jsdelivr.net', 'cdnjs.cloudflare.com'):
        assert zakazane not in strona


def test_eksplorator_nie_laduje_chartjs(strona):
    """Iskierki sa inline'owym SVG, tak jak w makiecie. Nie ma tu czego rysowac."""
    assert 'chart.umd.min.js' not in strona


def test_jest_przycisk_eksportu_widoku_i_arkusza(strona):
    assert 'id="eks-eksport"' in strona
    assert 'Eksport widoku' in strona
    assert 'href="/reports/arkusz"' in strona


def test_kontrolka_filtra_dziala_i_pokazuje_brak_gdy_pusto(strona):
    """W pierwszej wersji planu byla wylaczona. Od Zadania 9 ma popover."""
    fragment = strona.split('id="eks-filtr"')[1].split('>')[0]
    assert 'disabled' not in fragment
    assert '>brak<' in strona
    assert 'eks-kotwica-filtra' in strona


def test_kontrolka_filtra_pokazuje_skrot_warunku_i_krzyzyk(client):
    strona = client.get('/reports/eksplorator?wymiar=order_source'
                        '&filtr=wood_species:d%C4%85b').get_data(as_text=True)
    assert 'Gatunek: dąb' in strona
    assert 'id="eks-filtr-wyczysc"' in strona
    assert 'eks-ctl--wlaczony' in strona


def test_zly_filtr_w_adresie_nie_wywala_strony(client):
    odpowiedz = client.get('/reports/eksplorator?filtr=paid_cash:100')
    assert odpowiedz.status_code == 200
    assert '>brak<' in odpowiedz.get_data(as_text=True)


def test_strona_laduje_komponent_filtra_przed_eksploratorem(strona):
    assert strona.index('js/filtr.js') < strona.index('js/eksplorator.js')


def test_popover_filtra_dostaje_tylko_wymiary_proste(strona):
    """Po wymiarze zlozonym nie filtrujemy — jego wartosc to krotka."""
    fragment = strona.split("data-wymiary-filtra='")[1].split("'")[0]
    assert 'wood_species' in fragment
    assert 'konfiguracja' not in fragment


def test_zla_miara_w_adresie_nie_wywala_strony(client):
    assert client.get('/reports/eksplorator?miara=saldo').status_code == 200


# --- regresja z przegladu (Zadanie 12, przeglad) -----------------------------

def test_naglowek_panelu_miar_ma_pole_do_podmiany(strona):
    """rysujMiary() (eksplorator.js) czysci wylacznie cialo i stopke tabeli,
    NIE thead — bez data-pole na tej komorce zmiana wymiaru po stronie
    klienta zostawialaby w naglowku poprzedni wymiar."""
    assert 'data-pole="miary.naglowek"' in strona


def test_kotwica_filtra_ma_stale_id_do_przelaczania_klasy(strona):
    """JS przelacza eks-ctl--wlaczony po kazdym fetchu (zmiana filtra nie
    przeladowuje strony) — potrzebuje stalego uchwytu na kotwice."""
    assert 'id="eks-kotwica-filtra"' in strona


def test_krzyzyk_filtra_jest_zawsze_w_dom_i_ukryty_gdy_pusto(strona):
    """Krzyzyk musi istniec w DOM od startu (z atrybutem hidden), zeby
    podepnijFiltr() — wiazane raz, na starcie — mogl podpiac na nim nasluch.
    Element dodany do DOM dopiero po ustawieniu filtra nigdy by go nie dostal."""
    fragment = strona.split('id="eks-filtr-wyczysc"')[1].split('>')[0]
    assert 'hidden' in fragment


def test_krzyzyk_filtra_nie_jest_ukryty_gdy_filtr_ustawiony(client):
    strona = client.get('/reports/eksplorator?wymiar=order_source'
                        '&filtr=wood_species:d%C4%85b').get_data(as_text=True)
    fragment = strona.split('id="eks-filtr-wyczysc"')[1].split('>')[0]
    assert 'hidden' not in fragment


def test_panel_ma_przewijanie_poziome_dla_szerokiego_przestawienia():
    """.an-karta ma overflow: hidden, a .eks-tabela th/td maja white-space:
    nowrap — bez wlasnego overflow-x panel po cichu obcinalby prawe kolumny
    (Trend, Zmiana) przy przestawieniu z wieloma kolumnami (np. wojewodztwa:
    16 + wymiar + Trend + Zmiana = 19)."""
    sciezka = os.path.join(KORZEN, 'modules', 'reports', 'static', 'css', 'analiza.css')
    css = open(sciezka, encoding='utf-8').read()
    fragment = css.split('.eks-panel {')[1].split('}')[0]
    assert 'overflow-x' in fragment


# --- eksplorator.js ---------------------------------------------------------

def test_js_nie_wstawia_danych_przez_innerhtml(js):
    assert '.innerHTML =' not in js
    assert 'insertAdjacentHTML' not in js


def test_js_buduje_iskierki_jako_svg(js):
    assert 'createElementNS' in js
    assert 'polyline' in js


def test_js_sortuje_po_dowolnej_kolumnie(js):
    assert 'data-sortuj' in js
    assert 'sort(' in js


def test_js_eksportuje_csv_z_biezacego_widoku(js):
    assert 'eks-eksport' in js
    assert 'text/csv' in js
    # Separator srednik + BOM: Excel w polskim ustawieniu inaczej nie rozdzieli
    # kolumn i pogubi ogonki.
    assert "';'" in js
    assert '\\ufeff' in js


def test_js_zapisuje_parametry_w_adresie(js):
    assert 'URLSearchParams' in js
    assert 'history.pushState' in js


def test_js_pokazuje_blad_po_polsku(js):
    assert 'Nie udało się' in js


def test_js_nie_przepisuje_adresu_doslownie_do_api(js):
    """?miara=saldo renderuje sie poprawnie (trasa cofa do 'netto'), ale
    przepisane doslownie do /api/eksplorator wracaloby jako 400."""
    assert 'bazowy + window.location.search' not in js
    assert 'parametryStanu' in js


def test_js_uzywa_tego_samego_komponentu_filtra_co_dashboard(js):
    assert 'FiltrWymiaru.otworz' in js
    assert "ustawParametry({ filtr: tekst })" in js


def test_js_czysci_filtr_krzyzykiem(js):
    assert 'eks-filtr-wyczysc' in js
    assert "ustawParametry({ filtr: '' })" in js


def test_js_uzupelnia_tytul_panelu_przestawienia(js):
    """Regresja: wypelnij() ustawiala tylko miary.tytul. Placeholder
    data-pole="przestawienie.tytul" nigdy nie byl wypelniany, wiec po zmianie
    wymiaru/przestawienia (fetch bez przeladowania) naglowek drugiego panelu
    zostawal z poprzednim wymiarem."""
    assert "ustaw('przestawienie.tytul'" in js


def test_js_uzupelnia_naglowek_panelu_miar(js):
    assert "ustaw('miary.naglowek'" in js


def test_js_przelacza_stan_kontrolki_filtra_po_kazdym_fetchu(js):
    """Regresja: stan kontrolki (eks-ctl--wlaczony + krzyzyk) byl renderowany
    wylacznie serwerowo — po zmianie filtra przez popover (fetch, bez
    przeladowania) kontrolka nie odzwierciedlala juz tego, co pokazywaly
    dane pod spodem."""
    assert 'eks-kotwica-filtra' in js
    assert "classList.toggle('eks-ctl--wlaczony'" in js
    assert '.hidden = !dane.filtr.tekst' in js


def test_szkielet_nie_pokazuje_trendu_gdy_os_nie_jest_czasem(client):
    """Kolumny „Trend" i „Zmiana" znikaja po wypelnieniu przez JS — szkielet
    nie ma nimi migac."""
    strona = client.get('/reports/eksplorator?wymiar=order_source'
                        '&przestawienie=caretaker&miara=netto').get_data(as_text=True)
    assert '>Trend<' not in strona
    assert '>Zmiana<' not in strona


def test_js_rysuje_trend_tylko_gdy_serwer_na_to_pozwala(js):
    """Bez tego iskierka liczy sie z szeregu, ktory nie jest szeregiem czasowym."""
    assert 'p.trend !== false' in js
    assert 'if (zTrendem)' in js


def test_js_mowi_wprost_o_wygaslej_sesji(js):
    """Przy 401 komunikat kierowal uzytkownika na „Sprawdz parametry
    w adresie" — czyli kazal szukac bledu tam, gdzie go nie ma."""
    assert 'odp.status === 401' in js
    assert 'Sesja wygasła' in js


def test_js_normalizuje_adres_po_wejsciu_ze_zlym_parametrem(js):
    """Trasa HTML po cichu cofa zly parametr do domyslnego, ale adresu nie
    zmienia: po wejsciu z ?miara=saldo strona pokazuje netto, a pasek adresu
    dalej klamie — i taka zakladka zostaje zapisana. Dashboard robi to samo
    przez history.replaceState."""
    assert 'history.replaceState' in js


def test_js_uzywa_etykiet_wartosci_w_podgladzie_filtra(js):
    # Cialo opiszFiltr: do pierwszego zamkniecia funkcji na poziomie modulu.
    fragment = js.split('function opiszFiltr')[1].split(chr(10) + '  }')[0]
    assert 'etykietyWartosci' in fragment
    assert 'mapa[w] || w' in fragment


def test_js_kolor_wiersza_idzie_za_wartoscia_nie_za_pozycja(js):
    """Regresja z przegladu (fala 3, KRYTYCZNE 1): KOLORY[i % KOLORY.length]
    (i = indeks PO POSORTOWANIU) bral kolor z POZYCJI wiersza w rankingu, nie
    z tozsamosci wartosci wymiaru — a kazdy panel (miary i przestawienie)
    liczyl 'i' OSOBNO. Ta sama wartosc dostawala rozny kolor w obu panelach,
    i zmienial go pod uzytkownikiem po samym kliknieciu naglowka sortowania.
    Zasada wiodaca projektu: kolor idzie za ENCJA, nigdy za jej pozycja."""
    assert 'KOLORY[i % KOLORY.length]' not in js
    assert 'KOLORY[j % KOLORY.length]' not in js
    assert re.search(r'function kolorWartosci\(etykieta\)', js), \
        'kolor ma byc funkcja WYLACZNIE etykiety wartosci, bez indeksu/pozycji'


def test_js_oba_panele_licza_kolor_ta_sama_funkcja_z_tego_samego_pola(js):
    """Niezmiennik miedzypanelowy (analiza_service.dane_eksploratora: „ta sama
    wartość ma tę samą etykietę w panelu miar i w wierszach przestawienia")
    dziala na kolor TYLKO jesli oba panele licza go IDENTYCZNIE — z tej samej
    funkcji i z tego samego pola (etykieta), a nie z osobno liczonego
    indeksu wiersza w kazdym z nich."""
    assert js.count('kolorWartosci(w.etykieta)') == 2, \
        'panel miar (rysujMiary) i panel przestawienia (rysujPrzestawienie) ' \
        'maja wywolywac kolorWartosci(w.etykieta) — jeden raz kazdy'


def test_kolor_wartosci_jest_deterministyczny_i_niezalezny_od_kolejnosci():
    """Dowod na konkretnych wartosciach, nie tylko na obecnosci wzorca w
    zrodle: ta sama etykieta MUSI dac ten sam kolor bez wzgledu na to, w
    jakiej kolejnosci/pozycji wiersze sa rysowane — to jest dokladnie
    niezmiennik, ktorego brakowalo przed naprawa (dwa panele liczace 'i'
    OSOBNO dawaly rozne kolory tej samej wartosci po posortowaniu)."""
    def kolor_referencyjny(etykieta, kolory):
        # Ten sam algorytm (hash + modulo), co kolorWartosci() w eksplorator.js —
        # test weryfikuje WLASNOSC (determinizm, niezaleznosc od pozycji),
        # nie duplikuje implementacji jako zrodlo prawdy.
        tekst = '' if etykieta is None else str(etykieta)
        h = 0
        for znak in tekst:
            h = ((h << 5) - h + ord(znak)) & 0xFFFFFFFF
            if h >= 0x80000000:
                h -= 0x100000000
        return kolory[abs(h) % len(kolory)]

    kolory = ['#0F7D94', '#ED6B24', '#6B5B8A', '#C2BAAF', '#F0A473', '#2C6E4B', '#A8420E']
    wartosci = ['Sklep', 'Allegro', 'OLX', 'Ręczne w BL', 'dąb', 'buk']
    # Ta sama wartosc na roznych POZYCJACH (symulacja: panel miar posortowany
    # malejaco po netto, panel przestawienia posortowany po sumie kolumn —
    # rozne kolejnosci tych samych szesciu wartosci) ma dac ten sam kolor.
    kolejnosc_a = wartosci
    kolejnosc_b = list(reversed(wartosci))
    kolory_a = {w: kolor_referencyjny(w, kolory) for w in kolejnosc_a}
    kolory_b = {w: kolor_referencyjny(w, kolory) for w in kolejnosc_b}
    assert kolory_a == kolory_b, 'kolor zalezny od kolejnosci wywolania — nie powinien byc'


def test_js_wyroznia_kolumne_biezaca_tylko_na_osi_czasu(js):
    """Ostatnia wartosc drugiego wymiaru nie jest niczym „biezacym", a od
    limitu kolumn bywa nia kolumna zbiorcza „Pozostale"."""
    assert 'function biezaca(i)' in js
    assert "zTrendem && i === p.kolumny.length - 1" in js
    assert "j === p.kolumny.length - 1" not in js


# --- jednostki --------------------------------------------------------------
# Ta sama zasada co na dashboardzie: jednostka podpisana RAZ, w naglowku
# kolumny, a nie doklejona do kazdej liczby w tabeli.

def test_kazda_kolumna_panelu_miar_ma_jednostke_w_naglowku(strona):
    from modules.reports.analiza_service import JEDNOSTKI_MIAR, MIARY_PANELU

    for miara in MIARY_PANELU:
        assert f'eks-jednostka">&#160;{JEDNOSTKI_MIAR[miara]}<' in strona, \
            f'kolumna {miara} bez jednostki'


def test_naglowki_panelu_miar_nazywaja_miare_a_nie_sama_jednostke(strona):
    """Dawniej dwie kolumny byly podpisane sama jednostka („m³", „zł / m³"),
    a reszta sama nazwa — czytelnik nie wiedzial, czy „Netto" to zlotowki."""
    for etykieta in ('Netto', 'Udział', 'Objętość', 'Zamówienia',
                     'Śr. zamówienie', 'Cena', 'Klienci', 'Nowi klienci'):
        assert f'>{etykieta}<span class="eks-jednostka"' in strona, \
            f'brak naglowka „{etykieta}" z osobna jednostka'


def test_tytul_panelu_przestawienia_podaje_miare_z_jednostka(strona):
    """Komorki przestawienia to jedna miara w kilkunastu kolumnach miesiecy —
    bez tego podpisu nie wiadomo, czy „191 677" to zlotowki, czy sztuki."""
    assert '· Netto\u00a0zł' in strona


def test_selektor_miary_przestawienia_pokazuje_jednostke(strona):
    for tekst in ('Netto zł', 'Objętość m³', 'Zamówienia szt.'):
        assert tekst in strona, f'brak opcji „{tekst}"'


def test_js_bierze_podpis_miary_z_payloadu_a_nie_sklada_go_sam(js):
    """Tytul panelu przepisuje JavaScript po kazdym fetchu — gdyby dokladal
    jednostke z wlasnej listy, po zmianie miary rozjechalby sie z serwerem."""
    assert 'dane.przestawienie.etykieta_miary' in js
    assert 'zł' not in js, 'jednostka waluty wpisana na sztywno w JavaScripcie'


def test_css_ma_wyciszony_styl_jednostki_w_naglowku():
    sciezka = os.path.join(KORZEN, 'modules', 'reports', 'static', 'css', 'analiza.css')
    css = open(sciezka, encoding='utf-8').read()
    assert '.eks-jednostka' in css
    blok = css.split('.eks-jednostka {', 1)[1].split('}', 1)[0]
    # Czerwien jest zarezerwowana dla bledow.
    assert '--bad' not in blok


# --- format liczb jak na pulpicie (kontrola końcowa, DROBNE 5) ---------------

def _definicja_formattera(zrodlo, zmienna):
    """Opcje `var <zmienna> = new Intl.NumberFormat(...)` bez białych znaków."""
    definicja = zrodlo.split(f'var {zmienna} = new Intl.NumberFormat', 1)[1].split(');', 1)[0]
    return re.sub(r'\s+', '', definicja)


def test_js_formatuje_liczby_tak_samo_jak_pulpit(js):
    """Pulpit grupuje tysiące od czterech cyfr (porządki końcowe, 3h), a
    Eksplorator, do którego prowadzą stopki kafelków, dalej pisał „2361
    zamówienia · 5755 pozycji" obok „2 361" na karcie. Formattery obu stron
    mają te same opcje: zaokrąglenie do parzystej i `useGrouping: 'always'`."""
    pulpit = open(os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'analiza.js'),
                  encoding='utf-8').read()
    for zmienna in ('fmt0', 'fmt1', 'fmt2'):
        assert "useGrouping:'always'" in _definicja_formattera(js, zmienna), zmienna
        assert _definicja_formattera(js, zmienna) == _definicja_formattera(pulpit, zmienna), \
            f'{zmienna} w Eksploratorze formatuje inaczej niż na pulpicie'


def test_js_liczniki_eksploratora_maja_spacje_tysiecy():
    """Dowód na żywym silniku: formatter Eksploratora pisze „2 361" (spacja
    niełamiąca, jak w całym Intl), tak jak pulpit. Wymaga Node — w obrazie
    dockera go nie ma, więc tam test się pomija."""
    import json
    import subprocess

    zrodlo = open(SCIEZKA_JS, encoding='utf-8').read()
    formattery = ''.join(
        f'var {z} = new Intl.NumberFormat'
        + zrodlo.split(f'var {z} = new Intl.NumberFormat', 1)[1].split(');', 1)[0] + ');'
        for z in ('fmt0', 'fmt1', 'fmt2'))
    skrypt = (formattery + 'console.log(JSON.stringify(['
              'fmt0.format(2361), fmt0.format(999), fmt1.format(2027.4), fmt2.format(1234.5)]));')
    try:
        wynik = subprocess.run([os.environ.get('NODE_BIN', 'node'), '-e', skrypt],
                               capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, OSError):
        pytest.skip('Node niedostepny w tym srodowisku')
    if wynik.returncode != 0:
        pytest.skip(f'silnik JS bez Intl NumberFormat v3: {wynik.stderr}')
    assert json.loads(wynik.stdout) == ['2 361', '999', '2 027,4', '1 234,50']
