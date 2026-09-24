# -*- coding: utf-8 -*-
"""Jedna wartość wymiaru, kilka ZAPISÓW — „Kurier" i „kurier" (24.09.2026).

Dane z BaseLinkera mają tę samą wartość zapisaną różnie: wielkością liter
(„Kurier" / „kurier"), spacją na końcu („pobranie " / „pobranie") i znakiem
diakrytycznym („Płatnośc" / „Płatność"). Kolumny sprzedaży mają kolację
`utf8mb4_unicode_ci`, więc MySQL traktuje takie zapisy jak JEDNĄ wartość:
`GROUP BY` robi z nich jedną grupę, a jako jej `wartosc` oddaje JEDEN z zapisów.
Który — rozstrzyga plan zapytania, więc zapytanie segmentu, zapytanie bez
wykluczeń czy zapytanie po miesiącach potrafią oddać tę samą grupę INNYM
zapisem niż zapytanie bazowe.

Kod, który zestawiał wyniki dwóch zapytań po DOKŁADNYM napisie, gubił wtedy
wiersz: na domyślnym kafelku „Dostawa" (VIII 2025, segment „kanał: personal")
wiersz segmentu pokazywał 0 zł / 0 szt. zamiast 46 586,17 zł / 238 szt.,
a ta kwota lądowała w „Pozostałe" segmentu. Eksplorator pokazywał „Formę
płatności" w 25 wierszach przestawienia zamiast 23 — jedna wartość rozbita na
dwa wiersze, bo w różnych miesiącach baza oddała ją różnym zapisem.

CO TE TESTY PILNUJĄ
===================
1. `klucz_grupy` idzie za kolacją bazy (sprawdzone na MySQL 8.4, 24.09.2026):
   bez wielkości liter, bez znaków diakrytycznych rozkładalnych (ą = a,
   ó = o), bez spacji na końcu (PAD SPACE); „ł" to NIE „l", tabulator na
   końcu i spacja na początku się liczą.
2. Każde miejsce, które zestawia wyniki DWÓCH zapytań po wartości wymiaru,
   dopasowuje po grupie: segment porównawczy (wiersze, ogon, „Pozostałe"),
   „poza mapą" segmentu, kolor kawałka koła (odniesienie bez wykluczeń),
   udział kanału w poprzednim okresie (Statystyki), klienci w panelu miar
   Eksploratora. Przestawienie Eksploratora scala zapisy jednej grupy w jeden
   wiersz i jedną kolumnę.
3. SQLite (testy) grupuje Z rozróżnianiem wielkości liter, więc tam „Kurier"
   i „kurier" to dwa wiersze. Dopasowanie po DOKŁADNYM zapisie ma wtedy
   pierwszeństwo — dwa wiersze bazy nie dostają jednego wiersza segmentu.

Zachowanie MySQL-a (jeden reprezentant grupy, różny w różnych zapytaniach)
podajemy przez podmianę `wg_wymiaru` — SQLite sam go nie odtworzy. Nazwy
w danych są fikcyjne.
"""
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import analiza_service, analytics, explorer
from modules.reports.analiza_service import (
    INDEKS_NEUTRALNY, KOLORY_KATEGORII, _mapa_porownania, _przydziel_kolory,
    _wniosek_kanal, dane_dashboardu, dane_eksploratora,
)
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.reports.uklad import Instancja

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)


@compiles(LONGTEXT, 'sqlite')
def _longtext_jako_text(typ, kompilator, **kw):
    return 'TEXT'


from modules.production.models import ProductionOrder  # noqa: F401,E402
from modules.users.models import User  # noqa: F401,E402
from modules.clients.models import Client  # noqa: F401,E402
import modules.quotes.models  # noqa: F401,E402

_TABLES = [m.__table__ for m in (SalesClient, SalesOrder, SalesOrderItem)]

OD, DO = date(2026, 9, 1), date(2026, 9, 21)
DOSTAWA = Instancja('dostawa', 'delivery_method')
SEGMENT = {'order_source': ['personal']}


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


def _zamowienie(bl_id, dzien, netto, sztuki, dostawa, kanal='shop',
                platnosc='Przelew', gatunek='dąb'):
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien, order_source=kanal,
                     current_status='Nowe', delivery_method=dostawa,
                     payment_method=platnosc)
    db.session.add(zam)
    db.session.flush()
    db.session.add(SalesOrderItem(
        order_id=zam.id, value_net=Decimal(netto), quantity=sztuki,
        total_volume=Decimal(sztuki) / 100, group_type='towar', wood_species=gatunek,
        technology='lity', wood_class='A/B', finish_state='surowy'))


def _dane_dostawy():
    """Wrzesień 2026. Karta „Dostawa" ma limit 3 wierszy, więc przy czterech
    grupach widać dwie, „Pozostałe (2)" i rozpisany ogon.

    Grupy (netto całości / w tym kanał „personal"):
    - „Kurier DPD" 1500 zł, 7 szt. — zapisy „Kurier DPD" (sklep 1000 zł / 4 szt.,
      personal 300 zł / 2 szt.) i „kurier DPD" (personal 200 zł / 1 szt.);
    - „Odbiór osobisty" 400 zł, 2 szt. — tylko sklep;
    - „Poczta Polska" 120 zł, 3 szt. — zapisy „Poczta Polska" (sklep 70 zł /
      2 szt.) i „poczta polska" (personal 50 zł / 1 szt.) — w OGONIE;
    - „Paczkomat" 100 zł, 1 szt. — personal, w ogonie.
    """
    _zamowienie(1, date(2026, 9, 2), '1000.00', 4, 'Kurier DPD')
    _zamowienie(2, date(2026, 9, 3), '300.00', 2, 'Kurier DPD', kanal='personal')
    _zamowienie(3, date(2026, 9, 4), '200.00', 1, 'kurier DPD', kanal='personal')
    _zamowienie(4, date(2026, 9, 5), '400.00', 2, 'Odbiór osobisty')
    _zamowienie(5, date(2026, 9, 6), '70.00', 2, 'Poczta Polska')
    _zamowienie(6, date(2026, 9, 7), '50.00', 1, 'poczta polska', kanal='personal')
    _zamowienie(7, date(2026, 9, 8), '100.00', 1, 'Paczkomat', kanal='personal')
    db.session.commit()


def _jak_mysql(monkeypatch, wybor_bazy=min, wybor_segmentu=max):
    """`wg_wymiaru` tak, jak odpowiada MySQL w kolacji utf8mb4_unicode_ci.

    Zapisy różniące się wielkością liter to JEDNA grupa (sumy razem), a jej
    `wartosc` to jeden z zapisów: w zapytaniu BEZ segmentu `wybor_bazy`
    (domyślnie pierwszy w porządku napisów, „Kurier DPD"), w zapytaniu
    segmentu `wybor_segmentu` (domyślnie ostatni, „kurier DPD") — tak jak baza
    wybiera reprezentanta po swojemu w każdym zapytaniu.
    """
    prawdziwe = analiza_service.wg_wymiaru

    def wg_wymiaru_mysql(nazwa, od, do, filtr=None):
        segment = bool(filtr) and 'order_source' in filtr
        grupy = {}
        for w in prawdziwe(nazwa, od, do, filtr=filtr):
            klucz = w['wartosc'].lower() if isinstance(w['wartosc'], str) else w['wartosc']
            if klucz not in grupy:
                grupy[klucz] = dict(w)
                continue
            g = grupy[klucz]
            g['wartosc'] = (wybor_segmentu if segment else wybor_bazy)(
                g['wartosc'], w['wartosc'])
            for miara in ('netto', 'objetosc', 'sztuki', 'zamowienia'):
                g[miara] += w[miara]
        return sorted(grupy.values(), key=lambda w: -w['netto'])

    monkeypatch.setattr(analiza_service, 'wg_wymiaru', wg_wymiaru_mysql)


# --- 1. klucz grupy = kolacja bazy -------------------------------------------

@pytest.mark.parametrize('a, b', [
    ('Kurier DPD', 'kurier DPD'),
    ('Kurier', 'KURIER'),
    ('pobranie ', 'pobranie'),                     # PAD SPACE: spacje na końcu
    ('odbiór osobisty ', 'Odbiór osobisty'),
    ('Płatnośc przy odbiorze', 'Płatność przy odbiorze'),  # ć = c
    ('Gotówka', 'gotowka'),                        # ó = o
    ('Dąb', 'dab'),                                # ą = a
    ('Straße', 'STRASSE'),                         # ß = ss
    (' ', ''),                                     # sama spacja = pusty napis
    (('Dąb', 'lity', 'A/B'), ('dąb', 'Lity', 'a/b')),  # wymiar złożony
])
def test_klucz_grupy_laczy_to_co_laczy_kolacja_bazy(a, b):
    from modules.reports.aggregates import klucz_grupy
    assert klucz_grupy(a) == klucz_grupy(b)


@pytest.mark.parametrize('a, b', [
    ('łoza', 'loza'),          # „ł" nie rozkłada się na „l" — baza je rozróżnia
    ('abc\t', 'abc'),          # tabulator to nie dopełnienie spacją
    (' abc', 'abc'),           # spacja na początku się liczy
    ('a-b', 'ab'),
    (None, ''),                # NULL i pusty napis to w GROUP BY dwie grupy
])
def test_klucz_grupy_rozroznia_to_co_rozroznia_kolacja_bazy(a, b):
    from modules.reports.aggregates import klucz_grupy
    assert klucz_grupy(a) != klucz_grupy(b)


def test_klucz_grupy_nie_rusza_wartosci_innych_niz_napis():
    from modules.reports.aggregates import klucz_grupy
    for wartosc in (None, 4, Decimal('2.50'), True, date(2026, 9, 1)):
        assert klucz_grupy(wartosc) == wartosc


# --- 2. segment porównawczy ----------------------------------------------------

def test_segment_dopasowuje_wiersz_ktory_baza_oddala_innym_zapisem(app, monkeypatch):
    """Przykład z weryfikacji (VIII 2025, „Dostawa", segment „personal"):
    wiersz segmentu pokazywał 0 zł / 0 szt., a jego kwota szła do „Pozostałe"."""
    _dane_dostawy()
    _jak_mysql(monkeypatch)
    dane = dane_dashboardu(OD, DO, [DOSTAWA], porownanie=SEGMENT)
    karta = dane['karty'][DOSTAWA.klucz]
    segment = dane['porownanie']['karty'][DOSTAWA.klucz]
    ogon_segmentu = dane['porownanie']['ogony'][DOSTAWA.klucz]

    assert [w['wartosc'] for w in karta['wiersze']] == ['Kurier DPD', 'Odbiór osobisty', None]
    assert (segment[0]['netto'], segment[0]['sztuki']) == (Decimal('500.00'), 3)
    assert (segment[1]['netto'], segment[1]['sztuki']) == (Decimal('0'), 0)
    # „Pozostałe (2)" segmentu to DOKŁADNIE jego ogon: Poczta Polska 50 zł
    # i Paczkomat 100 zł — nie kurier, który się nie dopasował.
    assert (segment[2]['netto'], segment[2]['sztuki']) == (Decimal('150.00'), 2)
    assert [w['wartosc'] for w in karta['ogon']] == ['Poczta Polska', 'Paczkomat']
    assert [(w['netto'], w['sztuki']) for w in ogon_segmentu] == [
        (Decimal('50.00'), 1), (Decimal('100.00'), 1)]
    # Suma wierszy segmentu = cały segment.
    assert sum(w['netto'] for w in segment) == Decimal('650.00')


def test_segment_na_sqlite_dwa_zapisy_to_dwa_wiersze_bez_podwojenia(app):
    """SQLite grupuje z rozróżnianiem wielkości liter: „Kurier DPD" i „kurier
    DPD" to dwa wiersze bazy i dwa wiersze segmentu. Każdy wiersz bazy
    dostaje SWÓJ wiersz segmentu (dokładny zapis ma pierwszeństwo) — dopasowanie
    po grupie nie może dać obu tego samego i policzyć kwoty dwa razy."""
    _dane_dostawy()
    dane = dane_dashboardu(OD, DO, [Instancja('kanal', 'delivery_method')],
                           porownanie=SEGMENT)
    klucz = 'kanal:delivery_method'
    karta = dane['karty'][klucz]
    segment = dane['porownanie']['karty'][klucz]
    ogon_segmentu = dane['porownanie']['ogony'][klucz]
    pary = {w['wartosc']: (s['netto'], s['sztuki'])
            for w, s in zip(karta['wiersze'] + karta['ogon'], segment + ogon_segmentu)
            if not w['zbiorczy']}
    assert pary['Kurier DPD'] == (Decimal('300.00'), 2)
    assert pary['kurier DPD'] == (Decimal('200.00'), 1)
    assert pary['Poczta Polska'] == (Decimal('0'), 0)
    assert pary['poczta polska'] == (Decimal('50.00'), 1)
    assert sum(w['netto'] for w in segment) == Decimal('650.00')


# --- 3. „poza mapą" segmentu ---------------------------------------------------

def test_poza_mapa_segmentu_dopasowuje_inny_zapis(monkeypatch):
    """Wartość spoza mapy („Dol" — ucięty zapis z BaseLinkera) w zapytaniu
    segmentu wraca jako „DOL". Dymek „poza mapą" ma dostać jej liczby, nie zera."""
    def statystyki(netto, sztuki, wartosc):
        return dict(analytics._puste_statystyki(), netto=Decimal(netto), sztuki=sztuki,
                    zamowienia=1, wartosc=wartosc)
    monkeypatch.setattr(analytics, 'sprzedaz_wg_wojewodztw', lambda od, do, filtr=None: {
        'obszary': {}, 'poza_mapa': [statystyki('80.00', 2, 'DOL'),
                                     statystyki('10.00', 1, '')]})
    mapa_bazy = {'obszary': [], 'poza_mapa': [{'wartosc': ''}, {'wartosc': 'Dol'}]}
    wynik = _mapa_porownania(OD, DO, SEGMENT, mapa_bazy)
    assert [(p['netto'], p['sztuki']) for p in wynik['poza_mapa']] == [
        (Decimal('10.00'), 1), (Decimal('80.00'), 2)]


# --- 4. kolor kawałka koła za grupą --------------------------------------------

def test_kolor_kawalka_idzie_za_grupa_a_nie_za_zapisem():
    """Odniesienie (bez wykluczeń) oddało gatunek jako „buk", widok
    z wykluczeniami — jako „Buk". To ta sama encja i ma mieć ten sam kolor,
    a nie neutralny kolor „spoza czołówki"."""
    odniesienie = [{'wartosc': 'dąb', 'zbiorczy': False},
                   {'wartosc': 'buk', 'zbiorczy': False},
                   {'wartosc': 'jesion', 'zbiorczy': False}]
    wiersze = [{'wartosc': 'Buk', 'zbiorczy': False},
               {'wartosc': 'JESION', 'zbiorczy': False},
               {'wartosc': 'grab', 'zbiorczy': False}]
    _przydziel_kolory(wiersze, [], odniesienie, [])
    assert [w['indeks_koloru'] for w in wiersze] == [
        KOLORY_KATEGORII[1], KOLORY_KATEGORII[2], INDEKS_NEUTRALNY]


def test_kolor_kawalka_dwa_zapisy_w_odniesieniu_to_dwa_kolory():
    """SQLite: „Buk" i „buk" to w odniesieniu dwa wiersze — każdy ze swoim
    kolorem. Dwa nieneutralne kawałki jednego koła nigdy nie dzielą koloru."""
    odniesienie = [{'wartosc': 'buk', 'zbiorczy': False},
                   {'wartosc': 'Buk', 'zbiorczy': False}]
    wiersze = [{'wartosc': 'Buk', 'zbiorczy': False},
               {'wartosc': 'buk', 'zbiorczy': False}]
    _przydziel_kolory(wiersze, [], odniesienie, [])
    assert [w['indeks_koloru'] for w in wiersze] == [KOLORY_KATEGORII[1], KOLORY_KATEGORII[0]]


# --- 5. Statystyki: udział kanału w poprzednim okresie -------------------------

def test_wniosek_o_kanale_znajduje_udzial_poprzedni_zapisany_inaczej():
    czolo = [{'wartosc': 'shop', 'etykieta': 'Sklep', 'udzial': Decimal('40.0')}]
    tekst = _wniosek_kanal(czolo, {'Shop': Decimal('34.4')})['tekst']
    assert 'wobec 34,4% w poprzednim okresie' in tekst


# --- 6. Eksplorator -------------------------------------------------------------

def test_eksplorator_klienci_w_wierszu_zapisanym_inaczej(app, monkeypatch):
    """Liczniki klientów to OSOBNE zapytanie — baza oddała w nim grupę kuriera
    innym zapisem niż w panelu miar. Wiersz ma dostać swoich klientów, nie zera."""
    _dane_dostawy()
    _jak_mysql(monkeypatch)
    prawdziwe = explorer.klienci_wg_wymiaru

    def klienci_mysql(nazwa, od, do, filtr=None):
        wynik = {k: v for k, v in prawdziwe(nazwa, od, do, filtr=filtr).items()
                 if not (isinstance(k, str) and k.lower() == 'kurier dpd')}
        wynik['KURIER DPD'] = {'klienci': 2, 'nowi': 1}
        return wynik
    monkeypatch.setattr(explorer, 'klienci_wg_wymiaru', klienci_mysql)
    dane = dane_eksploratora('delivery_method', 'miesiac', 'netto', OD, DO)
    wiersz = next(w for w in dane['miary']['wiersze'] if w['wartosc'] == 'Kurier DPD')
    assert (wiersz['klienci'], wiersz['nowi_klienci']) == (2, 1)


def test_przestawienie_scala_zapisy_jednej_grupy_w_jeden_wiersz(app):
    """W sierpniu grupa przyszła jako „Kurier", we wrześniu jako „kurier"
    i „KURIER " — przestawienie ma JEDEN wiersz tej wartości z obiema
    kolumnami miesięcy. Wiersz niesie zapis o największej kwocie."""
    _zamowienie(1, date(2026, 8, 10), '300.00', 2, 'Kurier')
    _zamowienie(2, date(2026, 9, 10), '200.00', 1, 'kurier')
    _zamowienie(3, date(2026, 9, 11), '50.00', 1, 'KURIER ')
    _zamowienie(4, date(2026, 9, 12), '70.00', 1, 'Odbiór osobisty')
    db.session.commit()
    wynik = explorer.przestawienie('delivery_method', 'miesiac', 'netto',
                                   date(2026, 8, 1), DO)
    assert [w['wartosc'] for w in wynik['wiersze']] == ['Kurier', 'Odbiór osobisty']
    assert wynik['wiersze'][0]['komorki'] == {
        '2026-08': Decimal('300.00'), '2026-09': Decimal('250.00')}
    assert wynik['suma']['suma'] == Decimal('620.00')


def test_przestawienie_scala_zapisy_jednej_grupy_w_jedna_kolumne(app):
    _zamowienie(1, date(2026, 9, 2), '300.00', 2, 'Kurier')
    _zamowienie(2, date(2026, 9, 3), '200.00', 1, 'kurier', kanal='allegro')
    _zamowienie(3, date(2026, 9, 4), '70.00', 1, 'Odbiór osobisty')
    db.session.commit()
    wynik = explorer.przestawienie('order_source', 'delivery_method', 'netto', OD, DO)
    assert [k['klucz'] for k in wynik['kolumny']] == ['Kurier', 'Odbiór osobisty']
    komorki = {w['wartosc']: w['komorki'] for w in wynik['wiersze']}
    assert komorki['allegro']['Kurier'] == Decimal('200.00')
    assert komorki['shop']['Kurier'] == Decimal('300.00')


def test_przestawienie_nazywa_wiersz_tym_samym_zapisem_co_panel_miar(app, monkeypatch):
    """Niezmiennik międzypanelowy Eksploratora: ta sama wartość ma tę samą
    etykietę w panelu miar i w wierszach przestawienia — także wtedy, gdy baza
    oddała ją w obu zapytaniach innym zapisem."""
    _zamowienie(1, date(2026, 9, 2), '300.00', 2, 'Kurier')
    _zamowienie(2, date(2026, 9, 3), '200.00', 1, 'kurier')
    _zamowienie(3, date(2026, 9, 4), '70.00', 1, 'Odbiór osobisty')
    db.session.commit()
    _jak_mysql(monkeypatch, wybor_bazy=max)
    dane = dane_eksploratora('delivery_method', 'miesiac', 'netto', OD, DO)
    assert [w['etykieta'] for w in dane['miary']['wiersze']] == ['kurier', 'Odbiór osobisty']
    assert [w['etykieta'] for w in dane['przestawienie']['wiersze']] == [
        'kurier', 'Odbiór osobisty']


def test_przestawienie_wymiar_na_obu_osiach_ma_ten_sam_zapis_w_kolumnie(app, monkeypatch):
    """Ten sam wymiar w wierszach i kolumnach: nagłówek kolumny nazywa grupę
    tym samym zapisem, co panel miar i wiersz przestawienia."""
    _zamowienie(1, date(2026, 9, 2), '300.00', 2, 'Kurier')
    _zamowienie(2, date(2026, 9, 3), '200.00', 1, 'kurier')
    _zamowienie(3, date(2026, 9, 4), '70.00', 1, 'Odbiór osobisty')
    db.session.commit()
    _jak_mysql(monkeypatch, wybor_bazy=max)
    dane = dane_eksploratora('delivery_method', 'delivery_method', 'netto', OD, DO)
    assert [k['etykieta'] for k in dane['przestawienie']['kolumny']] == [
        'kurier', 'Odbiór osobisty']
