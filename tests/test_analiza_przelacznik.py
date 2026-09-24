# -*- coding: utf-8 -*-
"""Przełącznik miary „zł / szt. / zł + szt." na kafelkach pulpitu — etap PULPIT
(24.09.2026). Etap SERWER (tests/test_analiza_sztuki.py) dał liczby obu miar
i opis przełącznika każdego kafelka; ten plik pilnuje widoku.

Cytat użytkownika: „do wykresów/statystyk pokazywanie sztuk. Tylko nie
zrobiłbym tego jako statystyki zaraz obok, tylko np. w prawym górnym rogu
przełącznik pomiędzy zł, szt. a porównaniem (porównanie mogło by zmieniać
wykres na słupkowy + krzywa z kwotami nałożona na nie)". Trzecia opcja nazywa
się „zł + szt.", nie „porównanie" — „porównanie" znaczy na pulpicie segment
porównawczy.

CO TE TESTY PILNUJĄ
===================
1. Przełącznik RENDERUJE SERWER (makro kafelka) — z tej samej funkcji
   `opcje_przelacznika`, z której powstaje `przelaczniki` payloadu. Kafelek bez
   przełącznika nie ma go wcale (nie: wyłączony).
2. Stoi w prawym górnym rogu nagłówka karty, a w kafelku KPI — nad wykresem,
   który przełącza (nagłówek KPI to pięć wskaźników, róg zajmuje piąty).
3. Obsługa klawiatury: grupa radiowa z jednym przystankiem Taba i strzałkami.
4. Tryb to stan WIDOKU: przełączenie niczego nie pobiera (obie miary są już
   w payloadzie), w trybie edycji przełącznika nie ma, a kafelki wracają do
   trybu domyślnego.
5. Napisy zależne od trybu (tytuł „Sprzedaż netto", nagłówek kolumny, podpis
   osi) renderuje serwer w wariantach; CSS pokazuje wariant bieżącego trybu.
   Jednostki z rejestru, nazwy trybów — ze stałych serwera.

Fikstury jak w tests/test_analiza_widok.py (tam uzasadnienie zaślepki
sidebara, blueprintu `production` i szimu LONGTEXT).
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
from modules.reports.analiza_service import (
    ETYKIETY_MIAR, ETYKIETY_TRYBOW, JEDNOSTKI_MIAR, TRYB_OBA, TRYB_SZT, TRYB_ZL,
    opcje_przelacznika,
)
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.reports.models_uklad import UkladDashboardu
from modules.reports.uklad import Instancja

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
from modules.quotes.models import QuoteStatus  # noqa: E402

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATYKA_PRODUKCJI = os.path.join(KORZEN, 'modules', 'production', 'static')
SCIEZKA_JS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'analiza.js')
SCIEZKA_CSS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'css', 'analiza.css')

_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    SalesClient, SalesOrder, SalesOrderItem, ProductionOrder, UkladDashboardu,
)]

TRYBY = (TRYB_ZL, TRYB_SZT, TRYB_OBA)

# Każdy typ kafelka i oba kształty karty województw (mapa i słupki), plus
# kafelki bez przełącznika — tak, żeby jedna strona pokazała wszystkie
# przypadki z tabeli etapu SERWER.
UKLAD = [
    Instancja('kpi'), Instancja('wnioski'), Instancja('kanal', 'order_source'),
    Instancja('opiekun', 'caretaker'), Instancja('mix', 'konfiguracja'),
    Instancja('klienci', 'liczba_zamowien'), Instancja('klienci', 'caretaker'),
    Instancja('wojewodztwo', 'delivery_state'), Instancja('wojewodztwo', 'order_source'),
    Instancja('naleznosci', 'wiek_zamowienia'), Instancja('lejek'),
    Instancja('wykonczenie', 'finish_state'), Instancja('dostawa', 'delivery_method'),
]

# Karty, których tytuł nazywa miarę („Sprzedaż netto według:") — w trybie
# sztuk ten tytuł kłamałby, więc mają drugi wariant.
TYTUL_NETTO = 'Sprzedaż netto według:'


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
def zupa(app, client):
    uzytkownik = User.query.filter_by(email='kontroler@woodpower.pl').one()
    db.session.add(UkladDashboardu(user_id=uzytkownik.id, uklad=[
        {'typ': i.typ, 'wymiar': i.wymiar} for i in UKLAD]))
    db.session.commit()
    odp = client.get('/reports/analiza')
    assert odp.status_code == 200
    strona = BeautifulSoup(odp.get_data(as_text=True), 'html.parser')
    assert [k.get('data-klucz') for k in strona.select('[data-kafelek]')] == \
        [i.klucz for i in UKLAD]
    return strona


@pytest.fixture()
def js():
    return open(SCIEZKA_JS, encoding='utf-8').read()


@pytest.fixture()
def css():
    return re.sub(r'/\*.*?\*/', '', open(SCIEZKA_CSS, encoding='utf-8').read(), flags=re.S)


def _kafelki(zupa):
    for wezel in zupa.select('[data-kafelek]'):
        yield wezel, opcje_przelacznika(wezel.get('data-typ'), wezel.get('data-wymiar'))


def _cialo_funkcji(zrodlo, nazwa):
    """Ciało funkcji JS od nagłówka do klamry na tym samym wcięciu."""
    poczatek = zrodlo.index('function %s(' % nazwa)
    wiersz = zrodlo.rfind('\n', 0, poczatek) + 1
    wciecie = zrodlo[wiersz:poczatek]
    koniec = zrodlo.index('\n' + wciecie + '}', poczatek)
    return zrodlo[poczatek:koniec]


def _widoki(element):
    return (element.get('data-widok-miary') or '').split()


def _regula(css, selektor):
    tresci = re.findall(r'(?:^|[}\n])\s*' + re.escape(selektor) + r'\s*\{([^}]*)\}', css)
    assert tresci, 'brak reguly %s w analiza.css' % selektor
    return '\n'.join(tresci)


# --- 1. przełącznik renderuje serwer ----------------------------------------

def test_kafelek_z_przelacznikiem_ma_grupe_radiowa_z_opcjami_z_serwera(zupa):
    for wezel, opcje in _kafelki(zupa):
        klucz = wezel.get('data-klucz')
        grupy = wezel.select('[data-przelacznik]')
        if opcje is None:
            # Brak przełącznika to BRAK — nie wyłączona kontrolka.
            assert grupy == [], klucz
            assert wezel.get('data-tryb-miary') is None, klucz
            assert wezel.select('[data-widok-miary]') == [], klucz
            continue
        assert len(grupy) == 1, klucz
        grupa = grupy[0]
        assert grupa.get('role') == 'radiogroup', klucz
        assert grupa.get('aria-label'), klucz
        assert grupa.get('data-domyslny') == opcje['domyslny'], klucz
        assert wezel.get('data-tryb-miary') == opcje['domyslny'], klucz
        radia = grupa.select('button')
        assert [r.get('data-opcja-miary') for r in radia] == \
            [o['tryb'] for o in opcje['opcje']], klucz
        assert [r.get_text(strip=True) for r in radia] == \
            [o['etykieta'] for o in opcje['opcje']], klucz
        for radio in radia:
            domyslne = radio.get('data-opcja-miary') == opcje['domyslny']
            assert radio.get('type') == 'button'
            assert radio.get('role') == 'radio'
            assert radio.get('aria-checked') == ('true' if domyslne else 'false')
            # Jeden przystanek Taba na grupę (wzorzec radiogroup).
            assert radio.get('tabindex') == ('0' if domyslne else '-1')


def test_trzecia_opcja_to_zl_plus_szt_a_nie_porownanie(zupa):
    """„Porównanie" znaczy na pulpicie segment porównawczy — ta sama etykieta
    ma wszędzie znaczyć to samo."""
    assert ETYKIETY_TRYBOW[TRYB_OBA] == \
        f"{JEDNOSTKI_MIAR['netto']} + {JEDNOSTKI_MIAR['sztuki']}"
    napisy = {r.get_text(strip=True) for r in zupa.select('[data-przelacznik] button')}
    assert napisy == set(ETYKIETY_TRYBOW.values())
    assert not any('orówn' in n for n in napisy)


def test_przelacznik_stoi_w_prawym_gornym_rogu_naglowka(zupa):
    for wezel, opcje in _kafelki(zupa):
        if opcje is None:
            continue
        grupa = wezel.select_one('[data-przelacznik]')
        if wezel.get('data-typ') == 'kpi':
            # Nagłówek KPI to pięć wskaźników — róg zajmuje piąty. Przełącznik
            # stoi więc nad wykresem, który przełącza, w prawym rogu ciała.
            wiersz = grupa.parent
            assert 'an-kpi__przelacznik' in wiersz.get('class')
            assert wiersz.parent.get('data-cialo') == 'kpi'
            nastepny = wiersz.find_next_sibling(True)
            assert 'an-wykres-kadr' in nastepny.get('class')
            continue
        glowa = grupa.parent
        klasy = glowa.get('class')
        assert 'an-karta__glowa' in klasy and 'an-karta__glowa--przelacznik' in klasy, \
            wezel.get('data-klucz')
        # Kolejność w nagłówku: tytuł (warianty), przełącznik, selektor „według".
        dzieci = [d for d in glowa.find_all(True, recursive=False)]
        assert 'an-karta__tytul' in dzieci[0].get('class')
        indeks = dzieci.index(grupa)
        assert all('an-karta__tytul' in d.get('class') for d in dzieci[:indeks])
        assert 'an-karta__wymiar' in dzieci[indeks + 1].get('class')


def test_przelacznik_nie_ma_identyfikatorow_ani_selecta(zupa):
    """Dwa kafelki tego samego typu nie mogą dzielić `id`, a `select.an-sel`
    poza opakowaniem przykrywał już raz całą stronę."""
    for grupa in zupa.select('[data-przelacznik]'):
        assert grupa.select('[id]') == [] and not grupa.get('id')
        assert grupa.select('select') == []


def test_kafelek_z_fragmentu_ma_przelacznik_swojego_wymiaru(client):
    """Mapa pokazuje jedną miarę naraz (dwie opcje); ten sam kafelek na innym
    wymiarze to lista słupków (trzy). Po zmianie wymiaru kafelek przychodzi
    z serwera od nowa — razem ze swoim przełącznikiem."""
    for wymiar, tryby in (('delivery_state', [TRYB_ZL, TRYB_SZT]),
                          ('order_source', [TRYB_ZL, TRYB_SZT, TRYB_OBA])):
        odp = client.get(f'/reports/api/kafelek?typ=wojewodztwo&wymiar={wymiar}')
        assert odp.status_code == 200
        kafelek = BeautifulSoup(odp.get_json()['html'], 'html.parser')
        assert [r.get('data-opcja-miary') for r in
                kafelek.select('[data-przelacznik] button')] == tryby


# --- 5. napisy zależne od trybu ---------------------------------------------

def test_warianty_widoku_uzywaja_wylacznie_trybow_serwera(zupa, css):
    tokeny = set()
    for element in zupa.select('[data-widok-miary]'):
        tokeny.update(_widoki(element))
    assert tokeny and tokeny <= set(TRYBY)
    # Każdy tryb ma regułę, która chowa warianty innych trybów.
    for tryb in TRYBY:
        selektor = (f'.an-kafelek[data-tryb-miary="{tryb}"] [data-widok-miary]'
                    f':not([data-widok-miary~="{tryb}"])')
        assert selektor in css, tryb
    blok = css.split(f'[data-widok-miary]:not([data-widok-miary~="{TRYB_OBA}"])', 1)[1]
    assert blok.lstrip().startswith('{') and 'display: none' in blok.split('}', 1)[0]


def test_tytul_nazywajacy_netto_ma_wariant_bez_netto(zupa):
    """„Sprzedaż netto według:" nad sztukami kłamałoby — ta sama etykieta ma
    znaczyć wszędzie to samo. Pierwszy tytuł zostaje złotówkowy: z niego
    składa się nazwa kafelka dla czytnika ekranu (tryb edycji jest zawsze
    w trybie domyślnym)."""
    for wezel, opcje in _kafelki(zupa):
        tytuly = wezel.select('.an-karta__tytul')
        if not tytuly or tytuly[0].get_text(strip=True) != TYTUL_NETTO:
            continue
        if opcje is None:
            continue
        assert _widoki(tytuly[0]) == [TRYB_ZL], wezel.get('data-klucz')
        inne = [t for t in tytuly[1:] if TRYB_SZT in _widoki(t)]
        assert len(inne) == 1, wezel.get('data-klucz')
        assert 'netto' not in inne[0].get_text().lower()
        assert set(_widoki(inne[0])) == {TRYB_SZT, TRYB_OBA}


def test_naglowek_kolumny_ma_warianty_z_jednostkami_rejestru(zupa):
    """Tryb „szt." podpisuje kolumnę sztukami, tryb „zł + szt." — dwiema
    kolumnami, każda ze swoją jednostką. Jednostki z rejestru."""
    zl, szt = JEDNOSTKI_MIAR['netto'], JEDNOSTKI_MIAR['sztuki']
    sprawdzone = 0
    for wezel, opcje in _kafelki(zupa):
        if opcje is None:
            continue
        for naglowek in wezel.select('.an-naglowek-kolumn'):
            jednostki = {tryb: [j.get_text(strip=True) for j in
                                naglowek.select('.an-naglowek-kolumn__jednostka')
                                if tryb in _widoki(j)] for tryb in TRYBY}
            assert jednostki[TRYB_ZL] == [zl], wezel.get('data-klucz')
            assert jednostki[TRYB_SZT] == [szt], wezel.get('data-klucz')
            assert jednostki[TRYB_OBA] == [szt, zl], wezel.get('data-klucz')
            sprawdzone += 1
    assert sprawdzone >= 6


def test_kpi_ma_wariant_sztuk_w_polu_sprzedazy(zupa):
    kpi = zupa.select_one('[data-kafelek][data-typ="kpi"]')
    pole = kpi.select_one('[data-pole="kpi.sztuki"]').parent
    assert pole is kpi.select_one('[data-pole="kpi.netto"]').parent
    # Tryb „zł + szt." zostawia w polu „Sprzedaż" ZŁOTÓWKI (główna liczba
    # kafelka), a sztuki idą pod nią dopiskiem (decyzja 24.09.2026) — wariant
    # sztuk widać tylko w samym trybie „szt.".
    for sciezka in ('kpi.sztuki', 'kpi.zmiana.sztuki', 'kpi.sztuki.porownanie'):
        assert set(_widoki(kpi.select_one(f'[data-pole="{sciezka}"]'))) == \
            {TRYB_SZT}, sciezka
    for sciezka in ('kpi.netto', 'kpi.zmiana.netto', 'kpi.netto.porownanie'):
        assert set(_widoki(kpi.select_one(f'[data-pole="{sciezka}"]'))) == \
            {TRYB_ZL, TRYB_OBA}, sciezka
    podpisy = [e for e in pole.select('.an-etykieta') if TRYB_SZT in _widoki(e)]
    assert len(podpisy) == 1
    assert JEDNOSTKI_MIAR['sztuki'] in podpisy[0].get_text()
    assert 'netto' not in podpisy[0].get_text().lower()
    # Pozostałe cztery wskaźniki nie mają wariantów.
    assert len(kpi.select('.an-kpi__pole [data-widok-miary]')) == \
        len(pole.select('[data-widok-miary]'))


def test_legenda_kpi_ma_warianty_trybow(zupa):
    legenda = zupa.select_one('[data-kafelek][data-typ="kpi"] .an-legenda')
    osie = {tryb: [e.get_text(' ', strip=True).replace(' ', ' ') for e in
                   legenda.select('.an-legenda__jednostka') if tryb in _widoki(e)]
            for tryb in TRYBY}
    assert osie[TRYB_ZL] == [f"oś pionowa: tys. {JEDNOSTKI_MIAR['netto']}"]
    assert osie[TRYB_SZT] == [f"oś pionowa: {JEDNOSTKI_MIAR['sztuki']}"]
    # „zł + szt." ma podpisy osi na samym wykresie (w kolorze serii), a legenda
    # nazywa obie serie.
    assert osie[TRYB_OBA] == []
    for seria in ('slupki', 'krzywa'):
        wpis = legenda.select_one(f'[data-legenda="{seria}"]')
        assert wpis is not None and TRYB_OBA in _widoki(wpis.parent), seria


def test_legenda_i_tabele_kol_i_mapy_maja_wariant_sztuk(zupa):
    zl, szt = JEDNOSTKI_MIAR['netto'], JEDNOSTKI_MIAR['sztuki']
    for klucz in ('klienci:liczba_zamowien', 'klienci:caretaker'):
        glowa = zupa.select_one(f'[data-klucz="{klucz}"] thead')
        warianty = {tryb: [e.get_text(' ', strip=True) for e in glowa.select('[data-widok-miary]')
                           if tryb in _widoki(e)] for tryb in (TRYB_ZL, TRYB_SZT)}
        assert warianty[TRYB_ZL] == [f"{ETYKIETY_MIAR['netto']} {zl}"], klucz
        assert warianty[TRYB_SZT] == [f"{ETYKIETY_MIAR['sztuki']} {szt}"], klucz
    poza = zupa.select_one('[data-klucz="wojewodztwo:delivery_state"] [data-poza-mapa] thead')
    assert [e.get_text(' ', strip=True) for e in poza.select('[data-widok-miary]')
            if TRYB_SZT in _widoki(e)] == [f"{ETYKIETY_MIAR['sztuki']} {szt}"]


def test_kontekst_kafelkow_daje_nazwy_miar_z_rejestru(app):
    from datetime import date
    from modules.reports.routers_analiza import _kontekst_kafelkow
    assert _kontekst_kafelkow(date(2026, 9, 1), date(2026, 9, 24))['etykiety_miar'] \
        is ETYKIETY_MIAR


# --- 3 i 4. zachowanie w przeglądarce (źródło analiza.js) --------------------

def test_js_zmiana_trybu_nie_wysyla_zadania(js):
    """Obie miary są już w payloadzie kafelka — przełączenie rysuje kafelek
    od nowa z tego, co przyszło, i niczego nie pobiera."""
    cialo = _cialo_funkcji(js, 'ustawTrybMiary')
    for zakazane in ('fetch(', 'pobierzKafelek', 'zaladuj(', 'wymienKafelek',
                     'podgladWymiaru'):
        assert zakazane not in cialo, zakazane
    assert 'rysujKafelek(wezel, wezel.danePulpitu)' in cialo
    assert "setAttribute('data-tryb-miary'" in cialo


def test_js_bierze_miary_trybu_z_payloadu_a_nie_z_wlasnej_listy(js):
    """Co rysuje tryb, mówi serwer (`przelaczniki[klucz].opcje[].miary`:
    pierwsza = słupki, druga = krzywa albo druga kolumna). JavaScript nie zna
    nazw trybów."""
    assert 'dane.przelaczniki' in js and '.miary' in js
    for tryb in TRYBY:
        assert f"'{tryb}'" not in js and f'"{tryb}"' not in js, tryb
    assert 'zł' not in js


def test_js_klawiatura_przelacznika_to_wzorzec_radiogroup(js):
    cialo = _cialo_funkcji(js, 'podepnijPrzelaczniki')
    for klawisz in ('ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'):
        assert f"'{klawisz}'" in cialo, klawisz
    assert 'preventDefault()' in cialo
    ustaw = _cialo_funkcji(js, 'ustawTrybMiary')
    assert 'tabIndex' in ustaw and "'aria-checked'" in ustaw


def test_js_przelacznik_kafelka_w_drodze_z_serwera_nie_reaguje(js):
    """Kafelek, który czeka na fragment z serwera (podgląd wymiaru, dociąganie
    brakującego), ma jeszcze stare liczby — a za chwilę zostanie wymieniony na
    nowy, w trybie domyślnym. Przełączenie w tej chwili przestawiłoby napisy
    (warianty w CSS) nad liczbami, których nie ma czym przerysować."""
    cialo = _cialo_funkcji(js, 'podepnijPrzelaczniki')
    assert cialo.count("getAttribute('aria-busy') === 'true'") == 2


def test_js_tryb_edycji_wraca_do_trybu_domyslnego(js):
    assert 'przywrocTrybyDomyslne()' in _cialo_funkcji(js, 'wlaczEdycje')
    cialo = _cialo_funkcji(js, 'przywrocTrybyDomyslne')
    assert "getAttribute('data-domyslny')" in cialo
    assert 'ustawTrybMiary(' in cialo


def test_js_wykres_dwoch_miar_ma_dwie_osie_od_zera_i_siatke_z_jednej(js):
    cialo = _cialo_funkcji(js, 'rysujTrend')
    assert js.count('new Chart(') == 2
    assert "type: 'line'" in cialo and "yAxisID: 'y1'" in cialo
    assert "position: 'right'" in cialo
    assert cialo.count('beginAtZero: true') >= 2
    assert 'drawOnChartArea: false' in cialo
    # Wspólny dymek: wszystkie serie miesiąca naraz, każda z jednostką swojej miary.
    assert "mode: 'index'" in cialo
    assert 'miara: p.dataset.miara' in cialo
    # Podpis osi z jednostką z payloadu, w kolorze serii.
    assert cialo.count('title: {') >= 2 and cialo.count('text: podpisOsi(') == 2
    assert 'jednostki[miara]' in _cialo_funkcji(js, 'podpisOsi')
    # Podpis osi słupków: ta sama barwa co słupki, ciemniejsza, bo to tekst
    # 10 px i potrzebuje kontrastu ≥ 4,5:1 (weryfikacja 24.09.2026).
    assert 'color: KOLOR_PODPISU_SLUPKOW' in cialo and 'color: KOLOR_KRZYWEJ' in cialo
    assert 'koloryMiesiecy(KOLOR_SLUPKOW_DWIE_OSIE)' in cialo


def test_js_rysuje_miare_trybu_przepisujac_karte_a_kolor_idzie_za_encja(js):
    """Funkcje rysujące czytają z wiersza `netto` i `udzial` (słupek i liczba
    obok — jedno pole). Tryb z inną pierwszą miarą PRZEPISUJE gotowe liczby
    tej miary pod te nazwy (jak kartaKubelkowa) — nic nie liczy. Tryb
    domyślny zwraca te same obiekty, co payload."""
    rysuj = _cialo_funkcji(js, 'rysujKafelek')
    assert 'kartaWMierze(' in rysuj and 'wierszeWMierze(' in rysuj
    wiersz = _cialo_funkcji(js, 'wierszWMierze')
    assert 'nowy.netto = w[miary[0]]' in wiersz
    assert 'nowy.udzial = w[pola.udzial]' in wiersz
    assert 'nowy.druga = w[miary[1]]' in wiersz
    assert 'if (!w || trybDomyslny(miary)) { return w; }' in wiersz
    assert 'nowa.najwiekszy = karta[pola.najwiekszy]' in _cialo_funkcji(js, 'kartaWMierze')
    for funkcja in ('wierszWMierze', 'wierszeWMierze', 'kartaWMierze', 'obszaryWMierze'):
        cialo = _cialo_funkcji(js, funkcja)
        for zakazane in (' / ', ' * ', 'reduce(', 'Math.', ' + '):
            assert zakazane not in cialo, (funkcja, zakazane)
    # Kolor kawałka: indeks z serwera, jeden na wiersz, niezależny od miary.
    assert 'kolorKawalka(w.indeks_koloru)' in _cialo_funkcji(js, 'rysujPierscien')
    assert 'indeks_koloru' not in wiersz


def test_js_mapa_w_trybie_sztuk_bierze_poziom_i_wiersz_dymka_z_payloadu(js):
    cialo = _cialo_funkcji(js, 'rysujMapeWojewodztw')
    assert 'dymek_sztuk' in cialo
    assert 'obszaryWMierze(mapa.obszary, miara)' in cialo
    assert 'polaMiary(miara).poziom' in _cialo_funkcji(js, 'obszaryWMierze')


def test_js_dopisek_kola_klientow_idzie_za_miara_trybu(js):
    """Weryfikacja 24.09.2026, WAŻNE 2: w trybie „szt." pod kołem stało „kawałki
    koła to netto". Dopisek to napis Z SERWERA — `uwaga` albo `uwaga_sztuk` —
    wybierany tak samo jak udział i środek koła: nazwą klucza miary
    (POLA_MIARY), przepisaną przez kartaWMierze pod `uwaga`."""
    assert "uwaga: 'uwaga'" in js and "uwaga: 'uwaga_sztuk'" in js
    assert 'nowa.uwaga = karta[pola.uwaga]' in _cialo_funkcji(js, 'kartaWMierze')
    assert "ustawW(kafelek, klucz + '.uwaga', karta.uwaga)" in _cialo_funkcji(
        js, 'rysujKarteKubelkowa')


def test_nazwa_dostepna_kola_klientow_ma_wariant_sztuk(zupa, js):
    """„Udział w wartości zamówień" nad kołem sztuk kłamałoby czytnikowi
    ekranu tak samo, jak dopisek pod kołem. Wariant renderuje serwer w atrybucie
    kanwy, analiza.js wybiera go miarą trybu."""
    for klucz in ('klienci:liczba_zamowien', 'klienci:caretaker'):
        kanwa = zupa.select_one(f'[data-klucz="{klucz}"] canvas')
        assert kanwa['aria-label'] == 'Udział w wartości zamówień'
        assert kanwa['data-etykieta-sztuki'] == 'Udział w sztukach produktów'
    cialo = _cialo_funkcji(js, 'rysujKoloKlientow')
    assert "getAttribute('data-etykieta-' + miara)" in cialo
    assert "setAttribute('aria-label'" in cialo


# --- 6. wygląd -----------------------------------------------------------------

def test_css_przelacznik_ma_cel_dotyku_akcent_marki_i_znika_w_edycji(css):
    opcja = _regula(css, '.an-przelacznik__opcja')
    assert re.search(r'min-height: (2[4-9]|[3-9]\d)px', opcja)
    assert re.search(r'min-width: (2[4-9]|[3-9]\d)px', opcja)
    assert "'IBM Plex Sans'" in opcja
    aktywna = _regula(css, '.an-przelacznik__opcja[aria-checked="true"]')
    assert '--accent' in aktywna
    for zakazane in ('--bad', '#B33A2B', '--warn', '#D98A16', '#FDEDCF'):
        assert zakazane not in aktywna, zakazane
    assert 'outline' in _regula(css, '.an-przelacznik__opcja:focus-visible')
    assert 'display: none' in _regula(css, '.analiza--edycja .an-przelacznik')


def test_css_naglowek_z_przelacznikiem_nie_rosnie(css):
    """Tytuł i przełącznik dzielą jeden wiersz nagłówka; przełącznik (24 px)
    wchodzi ujemnymi marginesami w odstęp nad i pod wierszem tytułu, więc
    nagłówek ma tę samą wysokość co bez niego."""
    glowa = _regula(css, '.an-karta__glowa--przelacznik')
    assert 'display: grid' in glowa
    assert 'minmax(0, 1fr) auto' in glowa
    grupa = _regula(css, '.an-karta__glowa--przelacznik > .an-przelacznik')
    marginesy = re.search(r'margin: (-?\d+(?:\.\d+)?)px 0 (-?\d+(?:\.\d+)?)px', grupa)
    assert marginesy
    wysokosc = 24 + float(marginesy.group(1)) + float(marginesy.group(2))
    # Wiersz tytułu: 13,5 px x 1,3 = 17,55 px.
    assert wysokosc <= 17.55


def test_kpi_w_trybie_zl_i_szt_ma_dopisek_sztuk_pod_kwota(js):
    """Dopisek sztuk pod kwotą netto KPI dokleja JS (bez innerHTML), a widać
    go wyłącznie w trybie „zł + szt." (reguła CSS)."""
    css = open(os.path.join(os.path.dirname(SCIEZKA_JS), '..', 'css', 'analiza.css'),
               encoding='utf-8').read()
    cialo = _cialo_funkcji(js, 'rysujKpi')
    assert "dopisek.className = 'an-kpi__dopisek-szt'" in cialo
    assert "k === 'netto' && dane.kpi.sztuki !== undefined" in cialo
    assert '.an-kafelek:not([data-tryb-miary="zl_szt"]) .an-kpi__dopisek-szt { display: none; }' in css


def test_os_sztuk_ma_calkowite_podzialki_a_podpis_osi_czytelny_kontrast(js):
    """Bez `precision: 0` oś sztuk przy małych danych pokazywała „0, 0, 0, 1, 1, 1";
    podpis osi słupków ma kontrast 5,0:1 zamiast 3,8:1 (weryfikacja 24.09.2026)."""
    assert 'if (!MIARY_W_TYSIACACH[miara]) { podzialki.precision = 0; }' in \
        _cialo_funkcji(js, 'podzialkiOsi')
    cialo = _cialo_funkcji(js, 'rysujTrend')
    assert cialo.count('podzialkiOsi(czcionkaOsi, ') == 3
    assert "callback: podzialkaOsi(" not in cialo
    assert "var KOLOR_PODPISU_SLUPKOW = '#766E64';" in js


def test_nazwa_przelacznika_nie_mowi_netto(zupa):
    """Nazwa grupy przełącznika nie zależy od trybu, więc nie może mówić
    „netto" — w trybie sztuk czytnik ekranu kłamałby (weryfikacja 24.09.2026)."""
    grupy = zupa.select('[data-przelacznik]')
    assert grupy
    for grupa in grupy:
        assert 'netto' not in grupa['aria-label'].lower(), grupa['aria-label']
