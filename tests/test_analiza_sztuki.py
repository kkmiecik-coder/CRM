# -*- coding: utf-8 -*-
"""Sztuki produktów obok złotówek — etap SERWER przełącznika „zł / szt. /
zł + szt." na kafelkach pulpitu (24.09.2026).

Cytat użytkownika: „Backend najpewniej jest w stanie wysłać liczbę sztuk poza
kwotą, więc do wykresów/statystyk pokazywanie sztuk … w prawym górnym rogu
przełącznik pomiędzy zł, szt. a porównaniem". Trzecia opcja nazywa się
„zł + szt.", nie „porównanie" — „porównanie" znaczy na pulpicie segment
porównawczy („Dodaj porównanie") i ta sama etykieta ma wszędzie znaczyć to samo.

CO TE TESTY PILNUJĄ
===================
1. „szt." to SZTUKI PRODUKTÓW: suma `quantity` pozycji bez usług (ta sama
   reguła, co przy m³ — „Suszenie usługowe 88m3" ma w ilości metry, nie
   sztuki). Anulowane i nieopłacone (E5) oraz wykluczenia z pól u góry
   pulpitu (E4/E8) działają tak samo jak dla netto.
2. Sztuki liczą się W TYM SAMYM zapytaniu co netto — żadnego dodatkowego
   zapytania na kafelek.
3. Payload niesie OBIE miary od razu, więc zmiana trybu nie wysyła żądania.
   Udziały % dla obu miar liczy serwer; kolor kawałka koła idzie za encją
   i nie zależy od miary.
4. Tryb domyślny („zł") jest dzisiejszym pulpitem: stare klucze payloadu
   zostają co do nazwy, dochodzą tylko nowe.

Fikstury jak w tests/test_analiza_wykluczenia.py (tam uzasadnienie bloku
„rejestr mapperów" i szimu LONGTEXT). Nazwy w danych są fikcyjne.
"""
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy import event
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import analytics, reports_bp
import modules.reports.routers_analiza  # noqa: F401 — dopisuje trasy do reports_bp
from modules.reports.aggregates import kpi, wg_wymiaru
from modules.reports.analiza_service import (
    ETYKIETY_MIAR, INDEKS_NEUTRALNY, JEDNOSTKI_MIAR, TRYB_OBA, TRYB_SZT, TRYB_ZL,
    TRYBY_TYPOW, dane_dashboardu, do_json, opcje_przelacznika,
)
from modules.reports.fields import POLA
from modules.reports.filters import filtr_z_wykluczen
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.reports.models_uklad import UkladDashboardu
from modules.reports.uklad import KATALOG, UKLAD_DOMYSLNY, Instancja, parsuj_uklad

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

_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    SalesClient, SalesOrder, SalesOrderItem, ProductionOrder, UkladDashboardu,
)]

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATYKA_PRODUKCJI = os.path.join(KORZEN, 'modules', 'production', 'static')

OD, DO = date(2026, 9, 1), date(2026, 9, 21)
OKRES = 'od=2026-09-01&do=2026-09-21'
DZIS = date(2026, 9, 21)
ANULOWANE = 138625   # service.STATUSY_POZA_SPRZEDAZA


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


def _zamowienie(bl_id, dzien, pozycje, kanal='shop', opiekun='Anna',
                wojewodztwo='Mazowieckie', client_id=None, status_id=None,
                pochodzenie=None):
    """pozycje: krotki (netto, sztuki, gatunek, grupa, wykończenie)."""
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien,
                     order_source=kanal, caretaker=opiekun, current_status='Nowe',
                     baselinker_status_id=status_id, delivery_method='Kurier',
                     delivery_cost=Decimal('10.00'), client_id=client_id,
                     client_origin=pochodzenie, delivery_state=wojewodztwo)
    db.session.add(zam)
    db.session.flush()
    for netto, sztuki, gatunek, grupa, wykonczenie in pozycje:
        usluga = grupa == 'usługa'
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal(netto), quantity=sztuki,
            # Usługa suszenia ma w ilości METRY SZEŚCIENNE — i dlatego nie
            # wchodzi ani do m³, ani do sztuk.
            total_volume=Decimal('0') if usluga else Decimal(sztuki) / 100,
            group_type=grupa, wood_species=gatunek,
            technology=None if usluga else 'lity',
            wood_class=None if usluga else 'A/B', finish_state=wykonczenie))
    return zam


def _dane():
    """Wrzesień 2026 (w sprzedaży): 11 sztuk produktów za 1750 zł.

    - zam. 1, klient 1, sklep, Anna, mazowieckie: dąb 3 szt. (1000 zł, surowy)
      i USŁUGA suszenia 88 „sztuk" (50 zł) — usługa nie jest sztuką;
    - zam. 2, klient 2, Allegro, Bartek, śląskie: buk 5 szt. (400 zł, lakierowany);
    - zam. 3, klient 1, sklep, Anna, BEZ województwa: dąb 2 szt. (200 zł,
      olejowany) i buk 1 szt. (100 zł, surowy);
    - zam. 4, klient 2, ANULOWANE: dąb 7 szt. (999 zł) — poza sprzedażą (E5).

    Poza wrześniem: zam. 5 (20.08.2026, klient 1) dąb 4 szt. za 300 zł — w
    okresie poprzednim KPI i w szeregu miesięcznym; zam. 6 (wrzesień 2025,
    bez klienta) dąb 6 szt. za 600 zł — w nakładce roku poprzedniego.

    Denormalizacja klientów tak, jak liczy ją `ingest.liczniki_klientow`
    (tylko sprzedaż): klient 1 — 3 zamówienia, 1650 zł; klient 2 — 1, 400 zł.
    """
    db.session.add_all([
        SalesClient(id=1, orders_count=3, lifetime_net=Decimal('1650.00')),
        SalesClient(id=2, orders_count=1, lifetime_net=Decimal('400.00')),
    ])
    db.session.flush()
    _zamowienie(1, date(2026, 9, 2), [('1000.00', 3, 'dąb', 'towar', 'surowy'),
                                      ('50.00', 88, None, 'usługa', None)],
                client_id=1)
    _zamowienie(2, date(2026, 9, 3), [('400.00', 5, 'buk', 'towar', 'lakierowany')],
                kanal='allegro', opiekun='Bartek', wojewodztwo='Śląskie', client_id=2)
    _zamowienie(3, date(2026, 9, 4), [('200.00', 2, 'dąb', 'towar', 'olejowany'),
                                      ('100.00', 1, 'buk', 'towar', 'surowy')],
                wojewodztwo=None, client_id=1)
    _zamowienie(4, date(2026, 9, 5), [('999.00', 7, 'dąb', 'towar', 'surowy')],
                client_id=2, status_id=ANULOWANE)
    _zamowienie(5, date(2026, 8, 20), [('300.00', 4, 'dąb', 'towar', 'surowy')],
                client_id=1)
    _zamowienie(6, date(2025, 9, 10), [('600.00', 6, 'dąb', 'towar', 'surowy')])
    db.session.commit()


def _dashboard(uklad, **kwargi):
    return dane_dashboardu(OD, DO, uklad, na_dzien=DZIS, **kwargi)


def _bez_buku():
    obecne = {'wood_species': ['dąb', 'buk'], 'technology': ['lity'],
              'wood_class': ['A/B'],
              'finish_state': ['surowy', 'lakierowany', 'olejowany']}
    return {'wood_species': ['buk']}, obecne


# --- rejestr: jednostka i nazwa miary ---------------------------------------

def test_jednostka_sztuk_idzie_z_rejestru_pol():
    """Jednostka NIGDY na sztywno w widoku — z rejestru pól, z pola ilości
    pozycji, które sumujemy."""
    assert JEDNOSTKI_MIAR['sztuki'] == POLA['quantity'].jednostka == 'szt.'
    assert ETYKIETY_MIAR['sztuki'] == 'Sztuki'


def test_etykiety_trybow_skladaja_sie_z_jednostek_rejestru():
    """„zł", „szt." i „zł + szt." — z jednostek, nie z napisów wpisanych
    obok. I żadna nie mówi „porównanie": to słowo ma na pulpicie inne
    znaczenie (segment porównawczy)."""
    opcje = opcje_przelacznika('kpi', None)['opcje']
    assert [o['tryb'] for o in opcje] == [TRYB_ZL, TRYB_SZT, TRYB_OBA]
    assert [o['etykieta'] for o in opcje] == [
        JEDNOSTKI_MIAR['netto'], JEDNOSTKI_MIAR['sztuki'],
        JEDNOSTKI_MIAR['netto'] + ' + ' + JEDNOSTKI_MIAR['sztuki']]
    assert [o['etykieta'] for o in opcje] == ['zł', 'szt.', 'zł + szt.']
    for o in opcje:
        assert 'porówn' not in o['etykieta'].lower()


# --- agregaty: sztuki w tym samym zapytaniu co netto --------------------------

def test_kpi_liczy_sztuki_produktow_bez_uslug_i_bez_anulowanych(app):
    _dane()
    wynik = kpi(OD, DO)
    assert wynik['netto'] == Decimal('1750.00')
    # 3 + 5 + 2 + 1. NIE 99 (usługa 88) i NIE 18 (anulowane 7).
    assert wynik['sztuki'] == 11
    assert isinstance(wynik['sztuki'], int)


def test_wykluczony_buk_odejmuje_dokladnie_sztuki_bukowe(app):
    """E4/E8: odznaczony „buk" wycina pozycje bukowe (5 + 1 szt.), a pozycja
    z pustym gatunkiem (usługa) zostaje — w sztukach i tak jej nie ma."""
    _dane()
    wykluczenia, obecne = _bez_buku()
    filtr = filtr_z_wykluczen(wykluczenia, obecne)
    assert kpi(OD, DO)['sztuki'] - kpi(OD, DO, filtr=filtr)['sztuki'] == 6
    assert kpi(OD, DO, filtr=filtr)['netto'] == Decimal('1250.00')


def test_wg_wymiaru_niesie_sztuki_kazdej_wartosci(app):
    _dane()
    wiersze = {w['wartosc']: w for w in wg_wymiaru('order_source', OD, DO)}
    assert wiersze['shop']['sztuki'] == 6
    assert wiersze['allegro']['sztuki'] == 5
    # Wymiar poziomu zamówienia: suma po wartościach == całość.
    assert sum(w['sztuki'] for w in wiersze.values()) == kpi(OD, DO)['sztuki']


def test_szereg_miesieczny_niesie_sztuki_takze_w_pustych_miesiacach(app):
    _dane()
    szereg = analytics.szereg_miesieczny(date(2026, 1, 1), DO)
    assert [p['sztuki'] for p in szereg] == [0, 0, 0, 0, 0, 0, 0, 4, 11]


class _LicznikZapytan:
    """Liczy zapytania SELECT dotykające tabel sprzedaży."""

    def __init__(self):
        self.zapytania = []

    def __call__(self, conn, cursor, instrukcja, parametry, kontekst, wiele):
        if instrukcja.lstrip().upper().startswith('SELECT') and 'sales_' in instrukcja:
            self.zapytania.append(instrukcja)

    def __enter__(self):
        event.listen(db.engine, 'before_cursor_execute', self)
        return self

    def __exit__(self, *reszta):
        event.remove(db.engine, 'before_cursor_execute', self)


@pytest.mark.parametrize('wywolanie, ile', [
    (lambda: kpi(OD, DO), 2),
    (lambda: wg_wymiaru('order_source', OD, DO), 1),
    (lambda: wg_wymiaru('konfiguracja', OD, DO), 1),
    (lambda: analytics.szereg_miesieczny(date(2026, 1, 1), DO), 1),
    (lambda: analytics.sprzedaz_wg_wojewodztw(OD, DO), 1),
    (lambda: analytics.klienci_wg_liczby_zamowien(), 1),
])
def test_sztuki_nie_kosztuja_dodatkowego_zapytania(app, wywolanie, ile):
    """Wymóg 5: SUM(CASE…) w TYM SAMYM zapytaniu co netto. Liczby zapytań
    są te same, co przed wprowadzeniem sztuk."""
    _dane()
    with _LicznikZapytan() as licznik:
        wywolanie()
    assert len(licznik.zapytania) == ile, licznik.zapytania


# --- payload: kafelek KPI i szereg miesięczny ------------------------------

def test_kpi_i_trend_w_payloadzie_niosa_sztuki(app):
    _dane()
    dane = _dashboard([Instancja('kpi')])
    assert dane['kpi']['sztuki'] == 11
    # Okres poprzedni (11–31 sierpnia): zam. 5, 4 szt. -> +175,0%.
    assert dane['kpi']['zmiana']['sztuki'] == Decimal('175.0')
    assert dane['trend']['biezacy'][8]['sztuki'] == 11
    assert dane['trend']['biezacy'][7]['sztuki'] == 4
    assert dane['trend']['poprzedni'][8]['sztuki'] == 6


def test_segment_porownawczy_niesie_sztuki_w_kpi_trendzie_i_kartach(app):
    _dane()
    dane = _dashboard([Instancja('kpi'), Instancja('kanal', 'order_source')],
                      porownanie={'order_source': ['allegro']})
    druga = dane['porownanie']
    assert druga['kpi']['sztuki'] == 5
    assert druga['trend'][8]['sztuki'] == 5
    baza = dane['karty']['kanal:order_source']['wiersze']
    assert [w['wartosc'] for w in baza] == ['shop', 'allegro']
    assert [w['sztuki'] for w in druga['karty']['kanal:order_source']] == [0, 5]


# --- payload: karty ze słupkami --------------------------------------------

def test_wiersze_kart_slupkowych_niosa_sztuki_i_udzial_sztuk(app):
    _dane()
    karta = _dashboard([Instancja('kanal', 'order_source')])['karty']['kanal:order_source']
    shop, allegro = karta['wiersze']
    assert (shop['sztuki'], allegro['sztuki']) == (6, 5)
    # Udział liczy SERWER, dla obu miar, tą samą regułą co `udzial`.
    assert (shop['udzial_sztuk'], allegro['udzial_sztuk']) == (Decimal('54.5'), Decimal('45.5'))
    # Kolejność i skład wierszy idą za złotówkami — przełączenie miary nie
    # przetasowuje listy (te same encje w tych samych miejscach).
    assert shop['netto'] > allegro['netto']


def test_wiersz_pozostale_i_rozpisany_ogon_niosa_sztuki(app):
    _dane()
    dane = _dashboard([Instancja('dostawa', 'finish_state')],
                      porownanie={'order_source': ['shop']})
    karta = dane['karty']['dostawa:finish_state']
    # Limit karty dostaw to 3 wiersze łącznie z „Pozostałe (2)".
    assert [w['etykieta'] for w in karta['wiersze']] == [
        'surowy', 'lakierowany', 'Pozostałe (2)']
    assert [w['sztuki'] for w in karta['wiersze']] == [4, 5, 2]
    assert [w['sztuki'] for w in karta['ogon']] == [2, 0]
    assert sum(w['sztuki'] for w in karta['wiersze']) == 11
    # Druga seria (sklep) wyrównana do tych samych wierszy i do ogona.
    assert [w['sztuki'] for w in dane['porownanie']['karty']['dostawa:finish_state']] == [4, 0, 2]
    assert [w['sztuki'] for w in dane['porownanie']['ogony']['dostawa:finish_state']] == [2, 0]


def test_rozbicie_kanalu_recznego_niesie_sztuki(app):
    _dane()
    _zamowienie(7, date(2026, 9, 6), [('150.00', 2, 'dąb', 'towar', 'surowy')],
                kanal='personal', pochodzenie='Detal')
    db.session.commit()
    dane = _dashboard([Instancja('kanal', 'order_source')],
                      porownanie={'order_source': ['personal']})
    assert [w['sztuki'] for w in dane['kanal_rozbicie']['wiersze']] == [2]
    assert [w['sztuki'] for w in dane['porownanie']['kanal_rozbicie']] == [2]


def test_opiekun_niesie_sztuki_z_wykluczeniami(app):
    _dane()
    wykluczenia, obecne = _bez_buku()
    karta = _dashboard([Instancja('opiekun', 'caretaker')], wykluczenia=wykluczenia,
                       obecne=obecne)['karty']['opiekun:caretaker']
    assert {w['wartosc']: w['sztuki'] for w in karta['wiersze']} == {'Anna': 5}


# --- payload: koła --------------------------------------------------------

def test_kolo_wykonczen_ma_udzial_sztuk_i_wlasny_srodek_a_kolor_bez_zmian(app):
    _dane()
    karta = _dashboard([Instancja('wykonczenie', 'finish_state')])[
        'karty']['wykonczenie:finish_state']
    assert [w['etykieta'] for w in karta['wiersze']] == [
        'surowy', 'lakierowany', 'Pozostałe (2)']
    assert [w['sztuki'] for w in karta['wiersze']] == [4, 5, 2]
    # Metoda największej reszty, jak na kole klientów: zaokrąglone osobno
    # dawały 36,4 + 45,5 + 18,2 = 100,1 (weryfikacja 24.09.2026).
    assert [w['udzial_sztuk'] for w in karta['wiersze']] == [
        Decimal('36.4'), Decimal('45.4'), Decimal('18.2')]
    assert sum(w['udzial_sztuk'] for w in karta['wiersze']) == Decimal('100.0')
    assert sum(w['udzial'] for w in karta['wiersze']) == Decimal('100.0')
    # Środek pierścienia dla każdej miary osobno: w zł dominuje surowy,
    # w sztukach — lakierowany.
    assert karta['najwiekszy']['etykieta'] == 'surowy'
    assert karta['najwiekszy_sztuk'] == {'etykieta': 'lakierowany',
                                         'udzial': Decimal('45.4')}
    # Kolor za ENCJĄ (feb751e): jeden zestaw wierszy, jeden kolor na
    # wartość — miara nie ma go jak przemalować.
    assert [w['indeks_koloru'] for w in karta['wiersze']] == [1, 2, INDEKS_NEUTRALNY]


def test_kolo_klientow_na_kubelkach_liczy_sztuki_z_calej_historii_sprzedazy(app):
    """Kubełki liczą netto z denormalizacji `lifetime_net` (cała historia,
    tylko sprzedaż). Sztuki tą samą definicją: pozycje zamówień klienta
    w sprzedaży, bez usług — klient 2 ma 5 szt., a nie 12 (anulowane 7)."""
    _dane()
    karta = _dashboard([Instancja('klienci', 'liczba_zamowien')])[
        'karty']['klienci:liczba_zamowien']
    assert [(k['kubelek'], k['sztuki']) for k in karta['kubelki']] == [
        ('1 zam.', 5), ('2–3', 10), ('4–9', 0), ('10+', 0)]
    assert [w['sztuki'] for w in karta['wiersze']] == [5, 10, 0, 0]
    # Udziały do stu — metoda największej reszty, jak `udzial`.
    assert [w['udzial_sztuk'] for w in karta['wiersze']] == [
        Decimal('33.3'), Decimal('66.7'), Decimal('0'), Decimal('0')]
    assert karta['najwiekszy_sztuk'] == {'etykieta': '2–3', 'udzial': Decimal('66.7')}


def test_kolo_klientow_na_wymiarze_liczy_sztuki_za_okres(app):
    _dane()
    karta = _dashboard([Instancja('klienci', 'caretaker')])['karty']['klienci:caretaker']
    assert {w['wartosc']: w['sztuki'] for w in karta['wiersze']} == {'Anna': 6, 'Bartek': 5}
    assert sum(w['udzial_sztuk'] for w in karta['wiersze']) == Decimal('100.0')


# Dopisek pod kołem klientów na wymiarze — w trybie „zł" dokładnie ten, co
# przed przełącznikiem (tryb domyślny to dzisiejszy pulpit).
UWAGA_KOLA_NETTO = (
    'Uwaga: kawałki koła to netto zamówień złożonych w wybranym okresie. '
    'Konwersja i kubełki (wybór powyżej) liczą się z całej historii, '
    'a segment porównawczy tej karty nie dotyczy.')


def test_dopisek_pod_kolem_klientow_ma_wariant_trybu_sztuk(app):
    """Weryfikacja 24.09.2026, WAŻNE 2: w trybie „szt." koło pokazuje sztuki,
    a zdanie pod nim mówiło „kawałki koła to netto". Serwer podaje wariant
    dla sztuk (`uwaga_sztuk`) — ta sama treść, inna miara kawałka — a przy
    wykluczeniach ten sam dopisek o wykluczeniach co w wariancie „zł"."""
    _dane()
    wykluczenia, obecne = _bez_buku()
    for wykl, dopisek in ((None, ''), (wykluczenia, (
            ' Wykluczenia z pól u góry pulpitu działają na kawałki koła i nowych '
            'klientów, ale nie na konwersję ani kubełki.'))):
        karty = _dashboard([Instancja('klienci', 'caretaker'),
                            Instancja('klienci', 'liczba_zamowien')],
                           wykluczenia=wykl, obecne=obecne if wykl else None)['karty']
        wymiar = karty['klienci:caretaker']
        assert wymiar['uwaga'] == UWAGA_KOLA_NETTO + dopisek
        assert wymiar['uwaga_sztuk'] == (
            'Uwaga: kawałki koła to sztuki produktów (bez usług) z zamówień '
            'złożonych w wybranym okresie. Konwersja i kubełki (wybór powyżej) '
            'liczą się z całej historii, a segment porównawczy tej karty nie '
            'dotyczy.' + dopisek)
        assert 'netto' not in wymiar['uwaga_sztuk']
        # Zdanie o kubełkach nie nazywa miary — obowiązuje w obu trybach.
        kubelki = karty['klienci:liczba_zamowien']
        assert kubelki['uwaga_sztuk'] == kubelki['uwaga']


# --- payload: mapa ------------------------------------------------------------

def test_mapa_niesie_sztuki_i_poziom_kartogramu_dla_sztuk(app):
    _dane()
    dane = _dashboard([Instancja('wojewodztwo', 'delivery_state')],
                      porownanie={'order_source': ['allegro']})
    mapa = dane['karty']['wojewodztwo:delivery_state']['mapa']
    obszary = {o['id']: o for o in mapa['obszary']}
    assert (obszary['mazowieckie']['sztuki'], obszary['slaskie']['sztuki']) == (3, 5)
    assert mapa['maks_sztuk'] == 5
    assert obszary['slaskie']['poziom_sztuk'] == 5
    assert obszary['mazowieckie']['poziom_sztuk'] == 3
    # Kolor kartogramu w zł zostaje ten sam co dziś.
    assert (obszary['mazowieckie']['poziom'], obszary['slaskie']['poziom']) == (5, 2)
    assert [p['sztuki'] for p in mapa['poza_mapa']] == [3]
    # Dymek w trybie „szt." ma czym podpisać sztuki — nazwa i jednostka
    # z tych samych słowników co reszta pulpitu.
    assert mapa['dymek_sztuk'] == {'nazwa': 'sztuki', 'etykieta': 'Sztuki', 'miejsca': 0}
    # Lista wierszy dymka w trybie „zł" bez zmian.
    assert [m['nazwa'] for m in mapa['miary']] == list(analytics.MIARY_MAPY)
    druga = {o['id']: o for o in zip_obszary(mapa, dane['porownanie']['mapa'])}
    assert druga['slaskie']['sztuki'] == 5 and druga['mazowieckie']['sztuki'] == 0


def zip_obszary(mapa, druga):
    return [dict(liczby, id=baza['id'])
            for baza, liczby in zip(mapa['obszary'], druga['obszary'])]


# --- przełączniki ---------------------------------------------------------

def _tryby(opcje):
    return None if opcje is None else [o['tryb'] for o in opcje['opcje']]


@pytest.mark.parametrize('typ, wymiar, tryby', [
    ('kpi', None, [TRYB_ZL, TRYB_SZT, TRYB_OBA]),
    ('kanal', 'order_source', [TRYB_ZL, TRYB_SZT, TRYB_OBA]),
    ('kanal', 'wood_species', [TRYB_ZL, TRYB_SZT, TRYB_OBA]),
    ('opiekun', 'caretaker', [TRYB_ZL, TRYB_SZT, TRYB_OBA]),
    ('dostawa', 'delivery_method', [TRYB_ZL, TRYB_SZT, TRYB_OBA]),
    ('wojewodztwo', 'order_source', [TRYB_ZL, TRYB_SZT, TRYB_OBA]),
    # Mapa i koła: jedna miara naraz.
    ('wojewodztwo', 'delivery_state', [TRYB_ZL, TRYB_SZT]),
    ('wykonczenie', 'finish_state', [TRYB_ZL, TRYB_SZT]),
    ('klienci', 'liczba_zamowien', [TRYB_ZL, TRYB_SZT]),
    ('klienci', 'caretaker', [TRYB_ZL, TRYB_SZT]),
    # Bez przełącznika: tekst, osobne miary, saldo, wyceny.
    ('wnioski', None, None),
    ('mix', 'konfiguracja', None),
    ('naleznosci', 'wiek_zamowienia', None),
    ('naleznosci', 'caretaker', None),
    ('lejek', None, None),
])
def test_opcje_przelacznika_wedlug_typu_i_wymiaru(typ, wymiar, tryby):
    assert _tryby(opcje_przelacznika(typ, wymiar)) == tryby


def test_kazdy_typ_katalogu_ma_decyzje_o_przelaczniku():
    """Nowy typ kafelka bez wpisu to błąd programistyczny — łapie go test,
    nie produkcja (funkcja dla typu spoza mapy zwraca None, a nie wyjątek,
    żeby nie wywrócić pulpitu — lekcja M7)."""
    assert set(TRYBY_TYPOW) == set(KATALOG)
    assert opcje_przelacznika('nie-ma-takiego-typu', None) is None


def test_domyslny_tryb_to_zlotowki_a_miary_opcji_sa_w_payloadzie(app):
    _dane()
    for klucz, typ in KATALOG.items():
        opcje = opcje_przelacznika(klucz, typ.domyslny_wymiar)
        if opcje is None:
            continue
        assert opcje['domyslny'] == TRYB_ZL
        miary = {o['tryb']: o['miary'] for o in opcje['opcje']}
        assert miary[TRYB_ZL] == ['netto'] and miary[TRYB_SZT] == ['sztuki']
        if TRYB_OBA in miary:
            # Pierwsza miara = słupki (lewa oś / długość słupka), druga =
            # krzywa (prawa oś) albo druga kolumna liczb.
            assert miary[TRYB_OBA] == ['sztuki', 'netto']
        for miara in miary[TRYB_SZT] + miary[TRYB_ZL]:
            assert JEDNOSTKI_MIAR[miara] and ETYKIETY_MIAR[miara]


def test_payload_niesie_przelacznik_kazdej_instancji_ukladu(app):
    _dane()
    uklad = list(UKLAD_DOMYSLNY) + [Instancja('naleznosci', 'wiek_zamowienia'),
                                    Instancja('wojewodztwo', 'order_source')]
    dane = _dashboard(uklad)
    assert set(dane['przelaczniki']) == {i.klucz for i in uklad}
    for instancja in uklad:
        assert dane['przelaczniki'][instancja.klucz] == opcje_przelacznika(
            instancja.typ, instancja.wymiar)


def test_kafelek_z_fragmentu_niesie_swoj_przelacznik(client, app):
    _dane()
    odp = client.get('/reports/api/kafelek?typ=wojewodztwo&wymiar=delivery_state&' + OKRES)
    assert odp.status_code == 200
    dane = odp.get_json()['dane']
    assert dane['przelaczniki'] == {
        'wojewodztwo:delivery_state': do_json(opcje_przelacznika('wojewodztwo',
                                                                 'delivery_state'))}


def test_kontekst_kafelkow_daje_szablonowi_opcje_przelacznika(app):
    """Kafelki renderuje serwer — szablon ma dostać tę samą funkcję, z której
    powstaje `przelaczniki` w payloadzie, a nie własną listę opcji."""
    from modules.reports.routers_analiza import _kontekst_kafelkow
    assert _kontekst_kafelkow(OD, DO)['opcje_przelacznika'] is opcje_przelacznika


def test_tryb_przelacznika_nie_zapisuje_sie_w_ukladzie():
    """Zapisujemy wyłącznie układ. Pole „tryb" w pozycji układu jest błędem,
    a nie czymś, co serwer po cichu zapamięta."""
    from modules.reports.uklad import BladUkladu
    with pytest.raises(BladUkladu):
        parsuj_uklad({'uklad': [{'typ': 'kanal', 'wymiar': 'order_source', 'tryb': 'szt'}]})


# --- tryb domyślny: stare klucze zostają, dochodzą tylko nowe ----------------

def test_stare_klucze_payloadu_zostaja_a_nowe_sa_wylacznie_dopiskami(client, app):
    """Tryb „zł" to dzisiejszy pulpit. Kontrakt: każdy klucz sprzed zmiany
    jest na swoim miejscu; nowe klucze są wypisane tu z nazwy."""
    _dane()
    uklad = [Instancja('kpi'), Instancja('kanal', 'order_source'),
             Instancja('wykonczenie', 'finish_state'),
             Instancja('klienci', 'liczba_zamowien'),
             Instancja('wojewodztwo', 'delivery_state')]
    dane = _dashboard(uklad, porownanie={'order_source': ['allegro']})

    assert set(dane) - {'przelaczniki'} == {
        'okres', 'kpi', 'trend', 'karty', 'kanal_rozbicie', 'lejek',
        'dostawa_koszt_kuriera', 'wymiary_dostepne', 'jednostki', 'etykiety_miar',
        'segmenty', 'wykluczenia', 'porownanie', 'wnioski', 'pominietych'}
    assert set(dane['kpi']) - {'sztuki'} == {
        'netto', 'objetosc', 'zamowienia', 'saldo', 'srednie_zamowienie',
        'cena_za_m3', 'zmiana'}
    assert set(dane['kpi']['zmiana']) - {'sztuki'} == {
        'netto', 'objetosc', 'zamowienia', 'srednie_zamowienie', 'cena_za_m3'}
    assert set(dane['trend']['biezacy'][0]) - {'sztuki'} == {
        'rok', 'miesiac', 'netto', 'objetosc', 'zamowienia'}
    slupki = dane['karty']['kanal:order_source']['wiersze'][0]
    assert set(slupki) - {'sztuki', 'udzial_sztuk'} == {
        'wartosc', 'etykieta', 'netto', 'objetosc', 'zamowienia', 'udzial',
        'cena_za_m3', 'zbiorczy'}
    kolo = dane['karty']['klienci:liczba_zamowien']
    assert set(kolo['wiersze'][0]) - {'sztuki', 'udzial_sztuk'} == {
        'wartosc', 'etykieta', 'netto', 'zbiorczy', 'udzial', 'indeks_koloru'}
    assert set(kolo['kubelki'][0]) - {'sztuki'} == {'kubelek', 'klienci', 'netto'}
    mapa = dane['karty']['wojewodztwo:delivery_state']['mapa']
    assert set(mapa) - {'maks_sztuk', 'dymek_sztuk'} == {
        'miara', 'maks', 'poziomy', 'miary', 'obszary', 'poza_mapa'}
    assert set(mapa['obszary'][0]) - {'sztuki', 'poziom_sztuk'} == {
        'id', 'nazwa', 'ma_dane', 'poziom', 'netto', 'objetosc', 'zamowienia',
        'klienci', 'w_produkcji'}
    assert set(dane['porownanie']['karty']['kanal:order_source'][0]) - {'sztuki'} == {
        'netto', 'objetosc', 'zamowienia'}
    # Wartości trybu „zł" liczą się tak jak dotąd (udział, środek koła).
    assert slupki['udzial'] == Decimal('77.1')
    assert kolo['najwiekszy'] == {'etykieta': '2–3', 'udzial': Decimal('80.5')}
    # I to samo idzie przez trasę, tylko w JSON-ie.
    odp = client.get('/reports/api/analytics?' + OKRES)
    assert odp.status_code == 200
    assert 'przelaczniki' in odp.get_json()
    assert odp.get_json()['jednostki']['sztuki'] == 'szt.'
