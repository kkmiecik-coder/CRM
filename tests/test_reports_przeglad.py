# -*- coding: utf-8 -*-
"""
Podzakładka Raporty → PRZEGLĄD.

Przegląd jest INDEKSEM, nie kopią pozostałych podzakładek: nie ma ani jednego
własnego agregatu, wszystkie liczby cytuje z pięciu endpointów, które już
istnieją. Testy chronią dokładnie to, co przy takiej konstrukcji potrafi się
zepsuć po cichu:

1. DOMYŚLNOŚĆ. Sam wpis w `_PODZAKLADKI` NIE WYSTARCZA — o tym, co widzi
   użytkownik, decydują trzy stałe w reports-tab-content.html. Rozjazd między
   nimi a backendem daje albo podzakładkę nieosiągalną z paska, albo 404
   z paska. Do tego zapamiętany wybór w localStorage potrafi przykryć nową
   domyślną na zawsze — stąd test na przebity klucz pamięci.
2. LEKKOŚĆ KONTEKSTU. Fragment ma nie wykonywać agregatów; ciężkie liczby idą
   osobnymi żądaniami. Bez testu pierwszy „drobny wyjątek" wraca tu na stałe.
3. ZBIEŻNOŚĆ ?items=0. Wariant bez listy pozycji musi dawać CO DO LICZBY te
   same koszyki co wariant pełny — inaczej Przegląd i Terminy pokazywałyby dwie
   różne odpowiedzi na to samo pytanie.
4. KONTRAKTY, NA KTÓRYCH STOI FRONT. Nazwy koszyków, przynależność kodu
   segmentu do STATION_ORDER (rozdzielenie „po terminie na hali" od zaległości
   administracyjnej) i obecność `learning` w kopercie obsady — każde z nich
   jest w JS założeniem, którego JS nie umie sprawdzić.
5. ZASADY ARCHITEKTURY: zero Chart.js w podzakładce domyślnej, escapowanie
   wszystkiego, co przyszło z bazy, i jedno miejsce deklaracji kluczy
   localStorage.
"""
import os
import re
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog, ProductionStationEvent,
    ProductionStationEventWorker, ProductionWorker, ProductionWorkerSession,
)
from modules.production.services.station_catalog import STATION_ORDER
from modules.users.models import User
# configure_mappers() przy pierwszym zapytaniu konfiguruje CAŁY rejestr —
# bez tych importów wywala się na relationship('Multiplier') / ('Client').
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

BASE = '/production/api'
KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLONY = os.path.join(KORZEN, 'modules', 'production', 'templates')

# LONGTEXT (MySQL) nie istnieje w SQLite — jak w pozostałych pakietach.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

TABELE = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker, ProductionReworkLog,
)]

# Stały poniedziałek: dzień tygodnia bywa gałęzią (okno dni roboczych,
# agregacja tygodniowa), więc data nie może pochodzić z zegara maszyny.
PONIEDZIALEK = date(2026, 8, 10)


@pytest.fixture()
def app():
    app = Flask(__name__, template_folder=SZABLONY)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    # LOGIN_DISABLED neutralizuje login_required — testujemy ciało endpointów
    # i liczbę zapytań, nie Flask-Login.
    app.config['LOGIN_DISABLED'] = True

    from modules.production.routers.api import api_bp
    app.register_blueprint(api_bp, url_prefix=BASE)
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABELE)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def zalogowany(monkeypatch):
    """
    `reports_tab_content` loguje user_id także na ścieżce sukcesu, a testowa
    apka nie ma LoginManagera. Podmieniamy `current_user` w przestrzeni modułu
    (endpoint importuje go po nazwie), żeby test dotykał prawdziwego ciała
    endpointu, a nie jego kopii.
    """
    from modules.production.routers.api import reports_api

    monkeypatch.setattr(reports_api, 'current_user',
                        type('UzytkownikTestowy', (), {'id': 1, 'role': 'admin'})())
    return reports_api


class LicznikZapytan:
    """Zlicza zapytania SQL wykonane w bloku `with`."""

    def __init__(self, engine):
        self.engine = engine
        self.zapytania = []

    def __enter__(self):
        event.listen(self.engine, 'before_cursor_execute', self._zapisz)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, 'before_cursor_execute', self._zapisz)
        return False

    def _zapisz(self, conn, cursor, statement, parameters, context, executemany):
        self.zapytania.append(statement)

    def __len__(self):
        return len(self.zapytania)


_licznik = [0]


def _produkt(status='czeka_na_sklejanie', volume=0.5, quantity=10,
             deadline=None, utworzono=None):
    _licznik[0] += 1
    n = _licznik[0]
    order = ProductionOrder(baselinker_order_id=90000 + n,
                            internal_order_number=f'26/{n:05d}',
                            client_name='Klient Testowy')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id=f'26{n:03d}_1',
        product_sequence_in_order=1, original_product_name='Blat',
        quantity=quantity, volume_m3=volume, current_status=status,
        deadline_date=deadline,
        created_at=utworzono or datetime.combine(PONIEDZIALEK, time(9, 0)))
    db.session.add(produkt)
    db.session.commit()
    return produkt


def _event(produkt, station, delta, kiedy, source='mobile'):
    db.session.add(ProductionStationEvent(
        production_item_id=produkt.id, station_code=station, delta=delta,
        quantity_done_after=max(0, delta), created_at=kiedy, source=source))
    db.session.commit()


def _plik(*czesci):
    with open(os.path.join(*czesci), encoding='utf-8') as f:
        return f.read()


@pytest.fixture(scope='module')
def szkielet_html():
    return _plik(SZABLONY, 'components', 'reports-tab-content.html')


@pytest.fixture(scope='module')
def przeglad_html():
    return _plik(SZABLONY, 'components', 'reports', 'overview.html')


# ============================================================================
# 1. PRZEGLĄD JEST DOMYŚLNY — a to trzy stałe, nie jeden wpis w słowniku
# ============================================================================

def test_przeglad_jest_pierwszy_w_mapie_podzakladek():
    """
    Wpis 'przeglad' istnieje i stoi PIERWSZY w `_PODZAKLADKI`.

    Sama mapa nie decyduje o domyślnej podzakładce (robi to front), ale
    kolejność jest tu jedynym miejscem, w którym backend deklaruje zamiar —
    a whitelist bez wpisu oddaje 404 i podzakładka nie istnieje w ogóle.
    """
    from modules.production.routers.api.reports_api import _PODZAKLADKI

    assert 'przeglad' in _PODZAKLADKI
    assert list(_PODZAKLADKI)[0] == 'przeglad'
    _, szablon = _PODZAKLADKI['przeglad']
    assert szablon == 'components/reports/overview.html'
    assert os.path.exists(os.path.join(SZABLONY, 'components', 'reports', 'overview.html'))


def test_lista_podzakladek_frontu_zgadza_sie_z_backendem(szkielet_html):
    """
    PODZAKLADKI w szkielecie musi mieć DOKŁADNIE te same nazwy co `_PODZAKLADKI`.

    Nazwa spoza mapy backendu dostaje z paska 404; nazwa brakująca w liście
    frontu jest z paska nieosiągalna, choć endpoint ją zna. Ten test to jedyne
    miejsce, w którym da się to złapać przed użytkownikiem.
    """
    from modules.production.routers.api.reports_api import _PODZAKLADKI

    dopasowanie = re.search(r'const PODZAKLADKI = \[(.*?)\];', szkielet_html, re.S)
    assert dopasowanie, 'nie znaleziono deklaracji PODZAKLADKI w szkielecie'
    z_frontu = re.findall(r"'([a-z]+)'", dopasowanie.group(1))

    assert z_frontu == list(_PODZAKLADKI), (z_frontu, list(_PODZAKLADKI))


def test_domyslna_podzakladka_to_przeglad(szkielet_html):
    """
    PODZAKLADKA_DOMYSLNA i przycisk z klasą `active` muszą wskazywać Przegląd.

    Rozjazd tych dwóch daje najgorszy możliwy stan: pasek podświetla jedno,
    a panel ładuje drugie.
    """
    assert "const PODZAKLADKA_DOMYSLNA = 'przeglad';" in szkielet_html

    aktywne = re.findall(
        r'class="reports-subnav-btn[^"]*\bactive\b[^"]*"\s+data-sub="([a-z]+)"',
        szkielet_html)
    assert aktywne == ['przeglad'], aktywne

    # Kolejność przycisków w pasku ma odpowiadać kolejności pilności — Przegląd
    # jest pierwszy z lewej, bo jest wejściem.
    przyciski = re.findall(r'data-sub="([a-z]+)"', szkielet_html)
    assert przyciski[0] == 'przeglad'


def test_klucz_pamieci_podzakladki_zostal_przebity(szkielet_html):
    """
    Bez przebicia klucza NIKT, kto już był w Raportach, nie zobaczy Przeglądu.

    localStorage trzyma ostatni wybór; wszyscy dotychczasowi użytkownicy mają
    tam 'stanowiska', a `wybranaNaStarcie()` honoruje pamięć przed domyślną.
    Sufiks wersji daje jednorazowy reset — potem wybór znów jest respektowany,
    bo zapisuje się już pod nowym kluczem.
    """
    dopasowanie = re.search(r"const KLUCZ_PAMIECI = '([^']+)';", szkielet_html)
    assert dopasowanie, 'nie znaleziono KLUCZ_PAMIECI'
    assert dopasowanie.group(1) != 'reportsSubTab', (
        'klucz pamięci nie został przebity — stary wybór przykryje nową '
        'domyślną podzakładkę na zawsze')


# ============================================================================
# 2. KONTEKST FRAGMENTU JEST LEKKI
# ============================================================================

def test_fragment_przegladu_nie_wykonuje_agregatow(app, client):
    """
    Wejście na Przegląd nie może kosztować ani jednego agregatu.

    Wszystkie ciężkie liczby jadą osobnymi żądaniami (te same endpointy, z
    których korzystają pozostałe podzakładki). Dopuszczamy najwyżej JEDNO
    zapytanie: odczyt progu bezczynności z prod_config, cache'owany w serwisie
    konfiguracji — w ciepłym procesie to zero, na zimnym starcie jeden.
    """
    with app.app_context():
        _produkt()
        with LicznikZapytan(db.engine) as licznik:
            odp = client.get(f'{BASE}/reports/sub/przeglad')

        assert odp.status_code == 200
        assert len(licznik) <= 1, [str(q)[:120] for q in licznik.zapytania]


def test_fragment_przegladu_niesie_daty_z_zegara_aplikacji(app, client):
    """
    Fragment podaje frontowi „dziś" i początek okna przepływu Z SERWERA.

    Gdyby liczyła je przeglądarka, tablet albo laptop w innej strefie pytałby
    o inną dobę niż ta, którą serwis nazywa `as_of` — i Przegląd pokazywałby
    inny dzień niż podzakładka Terminy. Okno przepływu to 14 dni WŁĄCZNIE
    z dziś, czyli dziś − 13.
    """
    from modules.production.models import get_local_now

    with app.app_context():
        odp = client.get(f'{BASE}/reports/sub/przeglad')
        html = odp.get_data(as_text=True)

        dzis = get_local_now().date()
        assert f'const DZIS = "{dzis.isoformat()}"' in html
        assert (f'const PRZEPLYW_OD = "{(dzis - timedelta(days=13)).isoformat()}"'
                in html)

        # Kody stanowisk jadą z katalogu, a nie z listy literałów w JS.
        for kod in STATION_ORDER:
            assert f'"{kod}"' in html


def test_szkielet_raportow_dalej_kosztuje_dwa_agregaty(app, client, zalogowany):
    """
    Dołożenie Przeglądu nie ma prawa podrożyć WEJŚCIA na zakładkę Raporty.

    Pasek KPI liczy dwa agregaty (tydzień + liczba pozycji w systemie) i tyle
    ma zostać: podzakładka dociąga swoje dopiero po wstawieniu szkieletu.
    """
    with app.app_context():
        _produkt()
        with LicznikZapytan(db.engine) as licznik:
            odp = client.get(f'{BASE}/reports-tab-content')

        assert odp.status_code == 200
        assert len(licznik) == 2, [str(q)[:120] for q in licznik.zapytania]


# ============================================================================
# 3. ?items=0 — ta sama migawka, bez balastu
# ============================================================================

def _dane_terminow(app):
    """Trzy pozycje w trzech koszykach + jedna poza produkcją."""
    from modules.production.models import get_local_now

    dzis = get_local_now().date()
    _produkt(status='czeka_na_lakiernie', volume=0.5, quantity=4,
             deadline=dzis - timedelta(days=5))          # po terminie, na hali
    _produkt(status='czeka_na_logistyke', volume=0.25, quantity=8,
             deadline=dzis - timedelta(days=30))         # po terminie, poza halą
    _produkt(status='czeka_na_pakowanie', volume=0.1, quantity=3, deadline=dzis)
    _produkt(status='czeka_na_sklejanie', volume=0.2, quantity=5,
             deadline=dzis + timedelta(days=1))
    return dzis


def test_deadline_progress_items_0_gubi_liste_i_flage(app, client):
    """
    Przy ?items=0 z odpowiedzi znikają OBA klucze listy.

    Sam `items: []` nie wystarczy: serwis liczy `items_truncated` względem
    limitu, więc przy zerze zawsze mówiłby „lista przycięta" — przy pustej
    liście. Pole, którego nie ma, jest uczciwsze niż pole, które kłamie.
    """
    with app.app_context():
        _dane_terminow(app)

        odp = client.get(f'{BASE}/reports/deadline-progress?items=0')
        assert odp.status_code == 200
        dane = odp.get_json()

        assert 'items' not in dane
        assert 'items_truncated' not in dane
        assert dane['totals']['items_total'] == 4


def test_deadline_progress_bez_parametru_dalej_oddaje_liste(app, client):
    """
    Podzakładka Terminy nie może niczego zauważyć.

    ?items=0 jest DODATKIEM, nie zmianą domyślnego zachowania: lista pozycji
    napędza tam drill-down po kliknięciu w segment.
    """
    with app.app_context():
        _dane_terminow(app)

        dane = client.get(f'{BASE}/reports/deadline-progress').get_json()
        assert len(dane['items']) == 4
        assert dane['items_truncated'] is False


def test_deadline_progress_items_0_daje_te_same_koszyki_co_pelne(app, client):
    """
    ZBIEŻNOŚĆ: Przegląd i Terminy MUSZĄ podawać tę samą liczbę.

    To jedno wywołanie tej samej funkcji, więc różnica mogłaby wziąć się
    wyłącznie z pomyłki w endpoincie — a właśnie ona byłaby najtrudniejsza do
    zauważenia, bo oba ekrany wyglądałyby poprawnie osobno.
    """
    with app.app_context():
        _dane_terminow(app)

        pelne = client.get(f'{BASE}/reports/deadline-progress').get_json()
        chude = client.get(f'{BASE}/reports/deadline-progress?items=0').get_json()

        assert chude['buckets'] == pelne['buckets']
        assert chude['bucket_labels'] == pelne['bucket_labels']
        assert chude['totals'] == pelne['totals']
        assert chude['as_of'] == pelne['as_of']
        assert chude['datasets'] == pelne['datasets']


# ============================================================================
# 4. KONTRAKTY, NA KTÓRYCH STOI FRONT PRZEGLĄDU
# ============================================================================

def test_cztery_pilne_koszyki_istnieja_pod_swoimi_nazwami(app, client):
    """
    Przegląd bierze indeksy kafelków z `buckets`, nigdy z pozycji w liście.

    Ten test pilnuje drugiej połowy tej umowy: że nazwy, których Przegląd
    szuka, dalej w kontrakcie są. Przemianowanie koszyka w serwisie urwałoby
    Przeglądowi wszystkie cztery kafelki BEZ ŻADNEGO BŁĘDU — pokazałby zera.
    """
    with app.app_context():
        _dane_terminow(app)
        dane = client.get(f'{BASE}/reports/deadline-progress?items=0').get_json()

        for kod in ('po_terminie', 'dzis', '1_2_dni', '3_7_dni'):
            assert kod in dane['buckets'], kod

        # Suma czterech koszyków — jedyne miejsce, w którym Przegląd komponuje.
        indeksy = [dane['buckets'].index(k)
                   for k in ('po_terminie', 'dzis', '1_2_dni', '3_7_dni')]
        assert sum(dane['totals']['items'][i] for i in indeksy) == 4


def test_po_terminie_rozdziela_hale_od_zaleglosci_administracyjnej(app, client):
    """
    Kod segmentu spoza STATION_ORDER = „poza produkcją" — na tym stoi element 4.

    Bez tego rozdzielenia właściciel czyta „0.794 m³ po terminie na produkcji",
    co jest nieprawdą: dziś cała ta objętość stoi w Logistyce (niedomknięte
    zlecenie sprzed trzech miesięcy), a hala nie ma po terminie nic.
    """
    with app.app_context():
        _dane_terminow(app)
        dane = client.get(f'{BASE}/reports/deadline-progress?items=0').get_json()
        idx = dane['buckets'].index('po_terminie')

        na_hali, poza = {}, {}
        for ds in dane['datasets']:
            if not ds['items'][idx]:
                continue
            (na_hali if ds['code'] in STATION_ORDER else poza)[ds['code']] = ds['m3'][idx]

        assert 'painting' in na_hali, na_hali
        assert na_hali['painting'] == pytest.approx(2.0)      # 0.5 × 4
        assert 'czeka_na_logistyke' in poza, poza
        assert poza['czeka_na_logistyke'] == pytest.approx(2.0)  # 0.25 × 8


def test_stan_nauki_jedzie_razem_z_obsada_jednym_zadaniem(app, client):
    """
    Badge „Trwa nauka" i element „Wdrożenie profili" karmi JEDNO żądanie.

    `stan_nauki()` jest droga (pięć agregatów), a Przegląd potrzebuje jej
    w dwóch miejscach. Gdyby koperta obsady przestała nieść `learning`, front
    musiałby wołać osobny endpoint — czyli policzyć to samo drugi raz na jednym
    ekranie. Ten test broni właśnie tego, żeby nie było takiej pokusy.
    """
    with app.app_context():
        produkt = _produkt(status='czeka_na_sklejanie')
        _event(produkt, 'gluing', 3, datetime.combine(PONIEDZIALEK, time(9, 0)))

        dzien = PONIEDZIALEK.isoformat()
        dane = client.get(f'{BASE}/reports/staffing-vs-output'
                          f'?start_date={dzien}&end_date={dzien}').get_json()

        assert dane['success'] is True
        assert 'learning' in dane
        for klucz in ('learning', 'text', 'stations_with_profiles',
                      'stations_working', 'stations_without_profiles'):
            assert klucz in dane['learning'], klucz
        # Kafelek „osobogodzin dziś" i „m³ przerobu dziś" czytają summary.
        for klucz in ('person_hours', 'm3', 'open_sessions'):
            assert klucz in dane['summary'], klucz


def test_sesje_na_hali_niosa_wszystko_czego_potrzebuje_lista(app, client):
    """
    Wiersz „kto na hali" składa się wyłącznie z pól tej jednej koperty.

    `idle_over_timeout` jest tu najważniejszy: to on, a nie próg zaszyty
    w szablonie, decyduje o kolorze wiersza — próg mieszka w prod_config
    i admin zmienia go bez deployu.
    """
    with app.app_context():
        pracownik = ProductionWorker(first_name='Anna', last_name='Kowalska')
        db.session.add(pracownik)
        db.session.flush()
        db.session.add(ProductionWorkerSession(
            worker_id=pracownik.id, station_code='gluing',
            work_date=PONIEDZIALEK, session_group='g1',
            started_at=datetime.combine(PONIEDZIALEK, time(6, 0)),
            last_activity_at=datetime.combine(PONIEDZIALEK, time(6, 30))))
        db.session.commit()

        dane = client.get(f'{BASE}/workers/active-sessions').get_json()
        assert dane['success'] is True
        assert len(dane['sessions']) == 1
        sesja = dane['sessions'][0]
        for klucz in ('worker_name', 'station_label', 'started_at',
                      'idle_minutes', 'idle_over_timeout', 'pieces', 'm3'):
            assert klucz in sesja, klucz
        assert sesja['worker_name'] == 'Anna Kowalska'


def test_przeplyw_14_dni_jest_dzienny_i_ma_dzisiejszy_slupek(app, client):
    """
    Okno Przeglądu musi zostać PONIŻEJ progu agregacji tygodniowej.

    Powyżej 120 dni serwis zwraca ten sam kształt JSON, ale `date` to
    poniedziałek tygodnia — Przegląd narysowałby wtedy 14 słupków opisanych
    datami, które nie są dniami, i nie znalazłby „dnia w toku".
    """
    from modules.production.models import get_local_now

    with app.app_context():
        dzis = get_local_now().date()
        od = (dzis - timedelta(days=13)).isoformat()
        dane = client.get(f'{BASE}/reports/flow-in-out'
                          f'?start_date={od}&end_date={dzis.isoformat()}').get_json()

        assert dane['granularity'] == 'dzien'
        assert len(dane['days']) == 14
        assert dane['days'][-1]['date'] == dzis.isoformat()
        assert 'cumulative_end_m3' in dane and 'total_out_m3' in dane


# ============================================================================
# 5. ZASADY ARCHITEKTURY
# ============================================================================

def test_przeglad_nie_uzywa_chart_js(przeglad_html):
    """
    Podzakładka DOMYŚLNA nie ma prawa dokładać canvasów.

    Chart.js bierze rozmiar płótna w chwili rysowania, a panel podzakładki jest
    wypełniany, zanim staje się widoczny — cała machineria
    odswiezWykresyPanelu()/zniszczWykres()/posprzatajOsieroconeWykresy()
    w szkielecie istnieje wyłącznie z tego powodu. Przegląd ładuje się przy
    KAŻDYM wejściu na Raporty, więc paski rysuje CSS-em.
    """
    assert '<canvas' not in przeglad_html
    assert 'new Chart(' not in przeglad_html
    assert 'Chart.getChart' not in przeglad_html


def test_przeglad_nie_ma_wlasnego_bloku_stylow(przeglad_html):
    """
    Fragment wchodzi do DOM przez innerHTML — blok <style> zostawiałby po sobie
    kolejną kopię tych samych reguł przy każdym przeładowaniu podzakładki.
    Wygląd siedzi w static/css/reports-tab.css.
    """
    assert '<style' not in przeglad_html


def test_style_przegladu_sa_w_arkuszu_raportow():
    """Klasy .ov-* istnieją tam, gdzie reszta wyglądu zakładki."""
    css = _plik(KORZEN, 'modules', 'production', 'static', 'css', 'reports-tab.css')
    for klasa in ('.ov-stamp', '.ov-queue-row', '.ov-tile', '.ov-line',
                  '.ov-crew-row', '.ov-flow-day'):
        assert klasa in css, klasa
    # Przegląd dziedziczy kafelek po widgecie stanowiskowym, a nie definiuje
    # drugiej konwencji — te klasy muszą już w arkuszu być.
    for klasa in ('.report-widget', '.report-note', '.badge-nauka'):
        assert klasa in css, klasa


# Pola, które przyjeżdżają Z BAZY i lądują w HTML-u budowanym stringiem.
# Nazwiska pracowników i nazwy stanowisk to treść, nad którą aplikacja nie ma
# pełnej kontroli (katalog uzupełnia człowiek), a fragment wchodzi do DOM przez
# innerHTML — w tej zakładce był już potwierdzony XSS przez wstrzyknięcie do
# innerHTML, więc reguła jest bezwyjątkowa.
POLA_Z_BAZY = ('worker_name', 'station_label', 'station_code',
               's.label', 'nauka.text', 'braki.join')


def test_przeglad_escapuje_wszystko_co_przyszlo_z_bazy(przeglad_html):
    """
    Każda interpolacja pola z bazy do szablonu HTML idzie przez escapeHtml.

    Test czyta KAŻDE `${...}` w pliku i wymaga escapeHtml wszędzie tam, gdzie
    pada nazwa pola pochodzącego z bazy. To sito łapie dopisanie nowego wiersza
    metodą kopiuj-wklej z pominięciem funkcji — czyli dokładnie tę drogę, którą
    poprzednia podatność weszła.
    """
    # Wystarczy zgrubny podział na wyrażenia — interpolacje w tym pliku nie
    # zagnieżdżają nawiasów klamrowych.
    wyrazenia = re.findall(r'\$\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}', przeglad_html)
    assert wyrazenia, 'nie znaleziono żadnej interpolacji — test przestał działać'

    winne = [w for w in wyrazenia
             if any(pole in w for pole in POLA_Z_BAZY) and 'escapeHtml(' not in w]
    assert not winne, winne


def test_klucze_localstorage_sa_zadeklarowane_tylko_w_moscie(szkielet_html):
    """
    Nazwa klucza localStorage może istnieć w kodzie DOKŁADNIE RAZ.

    Przegląd zapisuje te same dwa klucze, które czyta stations.html (drill-down
    w stanowisko). Druga kopia literału daje najgorszy rodzaj awarii: zmiana
    jednej strony urywa drugą po cichu, bez błędu, a drill-down po prostu
    przestaje nastawiać widget.
    """
    stations = _plik(SZABLONY, 'components', 'reports', 'stations.html')
    przeglad = _plik(SZABLONY, 'components', 'reports', 'overview.html')

    for literal in ("'production.reports.station'",
                    "'production.reports.stationOutput'"):
        assert literal in szkielet_html, literal
        assert literal not in stations, (
            f'{literal} zdublowany w stations.html — klucz ma być tylko w moście')
        assert literal not in przeglad, (
            f'{literal} zdublowany w overview.html — klucz ma być tylko w moście')

    # …i most musi je faktycznie eksportować, inaczej fragmenty ich nie zobaczą.
    assert 'KLUCZE' in re.search(r'window\.ReportsShared = \{(.*?)\};',
                                 szkielet_html, re.S).group(1)
    assert 'wspolne.KLUCZE.stanowisko' in stations
    assert 'wspolne.KLUCZE.wykonanieStanowiska' in stations


def test_most_eksportuje_obie_funkcje_nawigacji(szkielet_html, przeglad_html):
    """
    Przegląd jest indeksem — bez tych dwóch funkcji każdy jego element jest
    ślepym zaułkiem. Funkcje żyją w szkielecie, bo tylko on widzi
    aktywujPodzakladke.
    """
    eksport = re.search(r'window\.ReportsShared = \{(.*?)\};',
                        szkielet_html, re.S).group(1)
    for nazwa in ('przejdzDoPodzakladki', 'przejdzDoStanowiska'):
        assert f'function {nazwa}(' in szkielet_html, nazwa
        assert nazwa in eksport, nazwa
        assert nazwa in przeglad_html, nazwa

    # Skok z kolejki nadpisuje preset ŚWIADOMIE — widget domyślnie wchodzi na
    # „Dziś", a stanowisko z rzadkim ruchem (lakiernia: 40 eventów na 14 dób
    # roboczych) wyglądałoby wtedy na zepsute.
    assert "preset || '30d'" in szkielet_html


def test_przeglad_nie_dubluje_widgetow_z_innych_podzakladek(przeglad_html):
    """
    Przegląd KIERUJE, a nie liczy po raz drugi.

    Trzy rzeczy, które przy dopisywaniu „jeszcze jednego kafelka" wracają
    najczęściej, a każda z nich dokładałaby drugą liczbę na to samo pytanie
    (albo trzecią kopię rozjazdu, który już mamy między paskiem KPI a widgetami):
      - pokrycie atrybucją — odpowiada na to samo co badge „Trwa nauka",
      - doróbki — zgłaszalne z 1 z 7 stanowisk, kafelek czytałby się odwrotnie,
      - heatmapa i historia synchronizacji — mają swoje podzakładki.
    """
    for endpoint in ('attribution-coverage', 'rework-registration',
                     'hourly-heatmap', 'station-output', 'worker-output',
                     'station-worker-output'):
        assert endpoint not in przeglad_html, endpoint

    # Pięć żądań i ani jednego więcej.
    zadania = re.findall(r"pobierzJson\(\s*[`'\"]([^`'\"]+)", przeglad_html)
    assert len(zadania) == 5, zadania
    assert any('items=0' in z for z in zadania), (
        'terminy muszą jechać bez listy pozycji — z nią odpowiedź waży 78 kB '
        'zamiast 3.5 kB')
