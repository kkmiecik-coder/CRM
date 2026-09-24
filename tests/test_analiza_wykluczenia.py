# -*- coding: utf-8 -*-
"""Pola wykluczeń na górze pulpitu: gatunek, technologia, klasa (partia E, E4)
i wykończenie (E8).

Cytat prezesa: „na górze dać checkboxy do wykluczania produktów … rozbicie
na gatunek, technologię i klasę". Pola buduje serwer z wartości faktycznie
obecnych w danych, a stan jedzie w ADRESIE (`?wyklucz=`), tak jak okres
i segment porównawczy — nie w zapisanym układzie.

PUŁAPKA, którą te testy zamykają: odznaczenie „buk" wyklucza TYLKO pozycje
bukowe. Pozycje z pustym gatunkiem (usługi, pozycje nierozpoznane) zostają
ZAWSZE. Naiwne `wood_species IN (zaznaczone)` wycięłoby je po cichu.

Poziom zamówienia (liczba zamówień, saldo) liczy zamówienia, które mają
CO NAJMNIEJ JEDNĄ niewykluczoną pozycję — jednym skorelowanym EXISTS, bez
joina z pozycjami (pułapka salda 7,58× z `filters.py`).

Fikstury jak w tests/test_analiza_api.py (tam uzasadnienie bloku „rejestr
mapperów" i szimu LONGTEXT).
"""
import html
import itertools
import os
import re
import sys
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import reports_bp
import modules.reports.routers_analiza  # noqa: F401 — dopisuje trasy do reports_bp
from modules.reports.aggregates import kpi
from modules.reports.analiza_service import (
    INDEKS_NEUTRALNY, KOLORY_KATEGORII, dane_dashboardu, do_json, wartosci_wykluczen,
)
from modules.reports.filters import (
    POLA_WYKLUCZEN, filtr_z_wykluczen, parsuj_wykluczenia, warunki_zamowienia,
    zapisz_filtr,
)
from modules.reports.fields import POLA
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.reports.models_uklad import UkladDashboardu
from modules.reports.uklad import KATALOG, UKLAD_DOMYSLNY, Instancja

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


def _zamowienie(bl_id, dzien, pozycje, saldo='0', kanal='shop', client_id=None,
                status='Nowe', koszt='10.00', pochodzenie=None, wojewodztwo=None,
                opiekun='Anna'):
    """pozycje: krotki (netto, objetosc, gatunek, technologia, klasa, grupa
    [, wykończenie]) — bez siódmego elementu pozycja jest surowa."""
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien,
                     balance_due=Decimal(saldo), order_source=kanal,
                     caretaker=opiekun, current_status=status,
                     delivery_method='Kurier', delivery_cost=Decimal(koszt),
                     client_id=client_id, client_origin=pochodzenie,
                     delivery_state=wojewodztwo)
    db.session.add(zam)
    db.session.flush()
    for netto, objetosc, gatunek, technologia, klasa, grupa, *reszta in pozycje:
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal(netto), total_volume=Decimal(objetosc),
            group_type=grupa, wood_species=gatunek, technology=technologia,
            wood_class=klasa, finish_state=reszta[0] if reszta else 'surowy',
            quantity=1))
    return zam


def _dane_bazowe():
    """Cztery zamówienia z września: dąb, buk, usługa bez cech i zamówienie
    MIESZANE (buk A/B + dąb B/B) — to ostatnie rozstrzyga, czy poziom
    zamówienia pyta o JEDNĄ pozycję spełniającą wszystkie warunki naraz."""
    _zamowienie(1, date(2026, 9, 2), [('1000.00', '0.10', 'dąb', 'lity', 'A/B', 'towar')],
                saldo='100.00')
    _zamowienie(2, date(2026, 9, 3), [('400.00', '0.05', 'buk', 'lity', 'A/B', 'towar')],
                saldo='200.00')
    _zamowienie(3, date(2026, 9, 4), [('50.00', '0', None, None, None, 'usługa')],
                saldo='300.00')
    _zamowienie(4, date(2026, 9, 5), [('70.00', '0.01', 'buk', 'mikrowczep', 'A/B', 'towar'),
                                      ('30.00', '0.01', 'dąb', 'lity', 'B/B', 'towar')],
                saldo='400.00')
    db.session.commit()


def _wyklucz(**pola):
    """Parametr adresu w formacie filtra: pole:wartosc|wartosc,..."""
    return ','.join(f'{nazwa}:' + '|'.join(quote(w, safe='') for w in wartosci)
                    for nazwa, wartosci in sorted(pola.items()))


def _filtry_stopek(znaczniki):
    """Parametr `filtr` z adresu każdej stopki kafelka, która prowadzi do
    Eksploratora, w kolejności na stronie. Brak parametru to ''. Stopka mapy
    prowadzi do mapy produkcji na starej zakładce i filtra nie ma z założenia."""
    adresy = [urlparse(html.unescape(adres)) for adres in re.findall(
        r'class="an-karta__stopka">\s*<a href="([^"]*)"', znaczniki)]
    return [parse_qs(adres.query).get('filtr', [''])[0] for adres in adresy
            if adres.path.endswith('/eksplorator')]


# --- lista pól budowana z danych ---------------------------------------------

def test_pola_wykluczen_to_cztery_grupy_w_kolejnosci_prezesa():
    """Gatunek, technologia, klasa (E4) i wykończenie (E8, dopisane przez
    użytkownika 23.09: „surowy, lakierowany, olejowany") — po klasie."""
    assert POLA_WYKLUCZEN == ('wood_species', 'technology', 'wood_class', 'finish_state')


def test_wartosci_pochodza_z_danych_bez_pustych_od_najwiekszego_netto(app):
    """Klasa A/A jest rzadka, ale w danych jest — pole musi dla niej powstać,
    inaczej liczyłaby się po cichu zawsze. Wartość pusta (usługi) pola nie
    dostaje: „brak wartości" zostaje zawsze i nie da się go odznaczyć."""
    with app.app_context():
        _dane_bazowe()
        _zamowienie(5, date(2025, 1, 5), [('5.00', '0.001', 'jesion', 'lity', 'A/A', 'towar')])
        _zamowienie(6, date(2025, 2, 5),
                    [('90.00', '0.01', 'dąb', 'lity', 'A/B', 'towar', 'olejowany'),
                     ('60.00', '0.01', 'dąb', 'lity', 'A/B', 'towar', 'lakierowany'),
                     ('40.00', '0', None, None, None, 'usługa', None)])
        db.session.commit()
        wartosci = wartosci_wykluczen()

    assert list(wartosci) == list(POLA_WYKLUCZEN)
    assert wartosci['wood_species'] == ['dąb', 'buk', 'jesion']
    assert wartosci['technology'] == ['lity', 'mikrowczep']
    assert wartosci['wood_class'] == ['A/B', 'B/B', 'A/A']
    assert wartosci['finish_state'] == ['surowy', 'olejowany', 'lakierowany']


def test_zdania_i_komunikaty_nie_wymieniaja_pol_z_pamieci():
    """JEDNO źródło listy pól: `POLA_WYKLUCZEN` z etykietami z rejestru.

    Do E8 trzy zdania (dopisek karty Klienci, zdanie przy tytule, uwaga
    lejka) i komunikat walidacji wymieniały „gatunek, technologię i klasę"
    z pamięci — czwarta grupa zostałaby w nich po cichu pominięta."""
    for sciezka in ('modules/reports/analiza_service.py', 'modules/reports/filters.py',
                    'modules/reports/templates/analiza/_kafelki.html',
                    'modules/reports/templates/analiza/dashboard.html'):
        with open(os.path.join(KORZEN, sciezka), encoding='utf-8') as plik:
            tekst = plik.read().lower()
        for wyliczenie in ('gatunku, technologii', 'gatunek, technologia, klasa',
                           'gatunku, technologii i klas'):
            assert wyliczenie not in tekst, (sciezka, wyliczenie)
    # Komunikat o obcym polu wymienia KAŻDĄ grupę, z etykietą z rejestru.
    with pytest.raises(ValueError) as blad:
        parsuj_wykluczenia('order_source:shop', OBECNE)
    for nazwa in POLA_WYKLUCZEN:
        assert POLA[nazwa].etykieta in str(blad.value), nazwa


# --- parsowanie i walidacja --------------------------------------------------

OBECNE = {'wood_species': ['dąb', 'buk', 'jesion'], 'technology': ['lity', 'mikrowczep'],
          'wood_class': ['A/B', 'B/B', 'A/A'],
          'finish_state': ['surowy', 'lakierowany', 'olejowany']}


def test_parsuje_odznaczone_wartosci_w_formacie_filtra():
    tekst = _wyklucz(wood_species=['buk'], wood_class=['B/B'])
    assert parsuj_wykluczenia(tekst, OBECNE) == {'wood_species': ['buk'],
                                                 'wood_class': ['B/B']}


def test_pusty_parametr_to_brak_wykluczen():
    for pusty in (None, '', '  '):
        assert parsuj_wykluczenia(pusty, OBECNE) is None


@pytest.mark.parametrize('tekst', [
    'order_source:shop',              # pole spoza trzech
    'wood_species:grab',              # wartości nie ma w danych
    'wood_species:',                  # „brak wartości" nie jest polem wyboru
    'wood_species:buk,wood_species:jesion',   # to samo pole dwa razy
    'nie-ma-dwukropka',
])
def test_zly_parametr_rzuca_blad_po_polsku(tekst):
    with pytest.raises(ValueError):
        parsuj_wykluczenia(tekst, OBECNE)


def test_nie_da_sie_odznaczyc_wszystkich_wartosci_grupy():
    """Pulpit pokazałby same zera — ostatnie zaznaczone pole jest blokowane
    w interfejsie, a adres, który to omija, odbija się błędem."""
    with pytest.raises(ValueError, match='co najmniej jedną'):
        parsuj_wykluczenia(_wyklucz(technology=['lity', 'mikrowczep']), OBECNE)


def test_filtr_z_wykluczen_to_zaznaczone_plus_brak_wartosci():
    """IN (zaznaczone) OR NULL/'' — istniejący mechanizm filtra, pusta
    wartość znaczy w nim „brak wartości"."""
    assert filtr_z_wykluczen({'wood_species': ['buk']}, OBECNE) == \
        {'wood_species': ['dąb', 'jesion', '']}
    assert filtr_z_wykluczen(None, OBECNE) is None


# --- semantyka na agregatach ---------------------------------------------------

def test_odznaczony_buk_wycina_tylko_pozycje_bukowe_a_usluga_zostaje(app):
    with app.app_context():
        _dane_bazowe()
        filtr = filtr_z_wykluczen({'wood_species': ['buk']}, OBECNE)
        bez = kpi(OD, DO)
        z = kpi(OD, DO, filtr=filtr)

    # 1000 + 400 + 50 + 70 + 30 = 1550; bez buku: 1000 + 50 + 30.
    assert bez['netto'] == Decimal('1550.00')
    assert z['netto'] == Decimal('1080.00')
    # Usługa (NULL) zostaje, zamówienie 2 (sam buk) wypada, mieszane zostaje.
    assert z['zamowienia'] == 3
    assert z['saldo'] == Decimal('800.00')


def test_grupy_lacza_sie_koniunkcja_a_zamowienie_potrzebuje_jednej_pozycji(app):
    """Odznaczone „buk" i „B/B": zamówienie 4 ma pozycje (buk, A/B) i (dąb, B/B)
    — KAŻDA wypada, więc zamówienie też. Dwa osobne EXISTS (po jednym na pole)
    liczyłyby je dalej: jedna pozycja spełnia warunek gatunku, druga klasy."""
    with app.app_context():
        _dane_bazowe()
        filtr = filtr_z_wykluczen({'wood_species': ['buk'], 'wood_class': ['B/B']}, OBECNE)
        wynik = kpi(OD, DO, filtr=filtr)

    assert wynik['netto'] == Decimal('1050.00')
    assert wynik['zamowienia'] == 2
    assert wynik['saldo'] == Decimal('400.00')


def test_pola_pozycji_wchodza_do_zamowienia_jednym_exists(app):
    with app.app_context():
        warunki = warunki_zamowienia({'wood_species': ['dąb'], 'wood_class': ['A/B']})
        sql = ' '.join(str(w) for w in warunki).upper()
    assert sql.count('EXISTS') == 1


def test_wykluczenie_nie_powiela_salda(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2),
                    [('100.00', '0.01', 'dąb', 'lity', 'A/B', 'towar')] * 20
                    + [('100.00', '0.01', 'buk', 'lity', 'A/B', 'towar')] * 14,
                    saldo='9969.32')
        db.session.commit()
        wynik = kpi(OD, DO, filtr=filtr_z_wykluczen({'wood_species': ['buk']}, OBECNE))
    assert wynik['saldo'] == Decimal('9969.32')
    assert wynik['zamowienia'] == 1


# --- pulpit: dane_dashboardu i trasy -------------------------------------------

def test_wszystkie_zaznaczone_to_co_do_znaku_ten_sam_payload(client, app):
    """Domyślnie wszystkie pola są zaznaczone, czyli brak wykluczeń — liczby
    identyczne z dzisiejszymi."""
    with app.app_context():
        _dane_bazowe()
    bez = client.get(f'/reports/api/analytics?{OKRES}').get_json()
    pusty = client.get(f'/reports/api/analytics?{OKRES}&wyklucz=').get_json()
    for dane in (bez, pusty):
        dane['okres'].pop('stan_na')
    assert bez == pusty


def test_payload_niesie_opis_wykluczen_i_filtr_wyjsc(client, app):
    with app.app_context():
        _dane_bazowe()
    tekst = _wyklucz(wood_species=['buk'], wood_class=['B/B'])
    dane = client.get(f'/reports/api/analytics?{OKRES}&wyklucz={tekst}').get_json()

    wyk = dane['wykluczenia']
    assert wyk['wykluczone'] == {'wood_species': ['buk'], 'wood_class': ['B/B']}
    assert wyk['opis'] == 'Bez: buk, B/B'
    assert wyk['tekst'] == zapisz_filtr({'wood_species': ['buk'], 'wood_class': ['B/B']})
    # Wyjścia do Eksploratora niosą to samo jako zwykły filtr (Eksplorator
    # rozumie `filtr`), z „brakiem wartości", który zostaje zawsze.
    assert wyk['filtr'] == zapisz_filtr({'wood_species': ['dąb', ''],
                                         'wood_class': ['A/B', '']})
    # Pigułka bazowa mówi, że liczby są bez części pozycji.
    assert dane['segmenty'][0]['nazwa'] == 'Bez: buk, B/B'
    assert dane['segmenty'][0]['wykluczenia'] is True
    assert 'buk' in wyk['zdanie']
    # KPI: 1550 - 400 - 70 - 30 = 1050.
    assert dane['kpi']['netto'] == 1050.0


def test_bez_wykluczen_pigulka_mowi_wszystkie_zamowienia(client, app):
    dane = client.get(f'/reports/api/analytics?{OKRES}').get_json()
    assert dane['segmenty'][0]['nazwa'] == 'Wszystkie zamówienia'
    assert dane['segmenty'][0]['wykluczenia'] is False
    assert dane['wykluczenia']['opis'] == ''
    assert dane['wykluczenia']['filtr'] == ''


def test_zly_parametr_na_api_to_400_po_polsku(client, app):
    with app.app_context():
        _dane_bazowe()
    for adres in (f'/reports/api/analytics?{OKRES}',
                  f'/reports/api/kafelek?typ=kpi&{OKRES}',
                  f'/reports/api/siatka?{OKRES}'):
        for zly in ('order_source:shop', 'wood_species:grab',
                    'technology:lity|mikrowczep'):
            odp = client.get(f'{adres}&wyklucz={zly}')
            assert odp.status_code == 400, (adres, zly)
            assert odp.get_json()['error'] == 'zle_wykluczenia'
            assert odp.get_json()['komunikat']


def test_zly_parametr_na_stronie_jest_ignorowany(client, app):
    with app.app_context():
        _dane_bazowe()
    odp = client.get(f'/reports/analiza?{OKRES}&wyklucz=wood_species:grab')
    assert odp.status_code == 200
    strona = odp.get_data(as_text=True)
    assert 'data-wyklucz=""' in strona


def test_strona_rysuje_pola_z_danych_i_zapamietuje_stan_z_adresu(client, app):
    with app.app_context():
        _dane_bazowe()
    tekst = _wyklucz(wood_species=['buk'])
    strona = client.get(f'/reports/analiza?{OKRES}&wyklucz={tekst}').get_data(as_text=True)
    # Trzy podpisane grupy, etykiety z rejestru pól.
    for etykieta in ('Gatunek', 'Technologia', 'Klasa'):
        assert f'>{etykieta}<' in strona
    assert f'data-wyklucz="{tekst}"' in strona
    # Odznaczony buk i zaznaczony dąb — stan przeżywa odświeżenie.
    buk = strona.split('value="buk"')[1].split('>')[0]
    dab = strona.split('value="dąb"')[1].split('>')[0]
    assert 'checked' not in buk
    assert 'checked' in dab
    # Pigułka i zdanie przy tytule od pierwszej klatki, bez czekania na dane.
    assert 'Bez: buk' in strona
    # Stopki kafelków też (weryfikacja E8, R6): każda niesie filtr wykluczeń,
    # ten sam, który potem przychodzi w payloadzie. analiza.js przepisuje je
    # dopiero po nadejściu danych, więc bez tego do tej chwili — albo na
    # zawsze, gdy rysowanie się wywróci — wyjście prowadzi do liczb z bukiem.
    filtr = client.get(f'/reports/api/analytics?{OKRES}&wyklucz={tekst}') \
                  .get_json()['wykluczenia']['filtr']
    filtry = _filtry_stopek(strona)
    assert filtr and filtry and set(filtry) == {filtr}
    # Bez wykluczeń stopki nie mają filtra — dowód, że oba stany się różnią.
    bez = client.get(f'/reports/analiza?{OKRES}').get_data(as_text=True)
    assert set(_filtry_stopek(bez)) == {''}


def test_ostatnie_zaznaczone_pole_grupy_jest_zablokowane(client, app):
    with app.app_context():
        _dane_bazowe()
    tekst = _wyklucz(technology=['mikrowczep'])
    strona = client.get(f'/reports/analiza?{OKRES}&wyklucz={tekst}').get_data(as_text=True)
    lity = strona.split('value="lity"')[1].split('>')[0]
    assert 'disabled' in lity and 'checked' in lity
    assert 'Zostaw co najmniej jedną wartość' in strona


def test_kafelek_i_siatka_niosa_wykluczenia(client, app):
    with app.app_context():
        _dane_bazowe()
    tekst = _wyklucz(wood_species=['buk'])
    tresc = client.get(f'/reports/api/kafelek?typ=kpi&{OKRES}&wyklucz={tekst}').get_json()
    assert tresc['dane']['kpi']['netto'] == 1080.0
    assert tresc['dane']['wykluczenia']['opis'] == 'Bez: buk'
    # Szkielet kafelka niesie filtr w stopce sam z siebie (weryfikacja E8, R3),
    # a nie dopiero po przepisaniu jej przez analiza.js z payloadu.
    filtr = tresc['dane']['wykluczenia']['filtr']
    assert filtr and _filtry_stopek(tresc['html']) == [filtr]

    siatka = client.get(f'/reports/api/siatka?{OKRES}&wyklucz={tekst}').get_json()['html']
    # Wyjście do Eksploratora niesie wykluczenia jako filtr.
    assert 'filtr=wood_species' in siatka


def test_segment_przecina_sie_z_wykluczeniami(client, app):
    """Segment „gatunek: buk" przy odznaczonym buku to pustka — koniunkcja,
    istniejące łączenie filtrów. Segment po innym wymiarze dostaje wykluczenia
    razem z nim."""
    with app.app_context():
        _dane_bazowe()
    tekst = _wyklucz(wood_species=['buk'])
    dane = client.get(f'/reports/api/analytics?{OKRES}&wyklucz={tekst}'
                      f'&porownanie=wood_species:buk').get_json()
    assert dane['porownanie']['kpi']['netto'] == 0
    dane = client.get(f'/reports/api/analytics?{OKRES}&wyklucz={tekst}'
                      f'&porownanie=order_source:shop').get_json()
    assert dane['porownanie']['kpi']['netto'] == 1080.0
    # Opis segmentu mówi o segmencie, nie o wykluczeniach.
    assert dane['porownanie']['nazwa'] == 'Kanał sprzedaży: Sklep'


def test_kazdy_typ_kafelka_liczy_z_wykluczeniami_albo_mowi_ze_nie(app):
    """Tabela z raportu: kafelki sprzedaży liczą bez wykluczonych pozycji,
    a kubełki klientów (cała historia) i lejek (wyceny) mówią wprost, że
    wykluczeń nie uwzględniają."""
    with app.app_context():
        _dane_bazowe()
        uklad = [Instancja(t, KATALOG[t].domyslny_wymiar if KATALOG[t].wymiarowy else None)
                 for t in KATALOG]
        bez = do_json(dane_dashboardu(OD, DO, uklad))
        z = do_json(dane_dashboardu(OD, DO, uklad,
                                    wykluczenia={'wood_species': ['buk']},
                                    obecne=OBECNE))

    def netto_kart(dane, klucz):
        return sum(w['netto'] for w in dane['karty'][klucz]['wiersze'])

    assert z['kpi']['netto'] == 1080.0
    for klucz in ('kanal:order_source', 'opiekun:caretaker', 'wojewodztwo:delivery_state',
                  'wykonczenie:finish_state', 'dostawa:delivery_method'):
        assert netto_kart(bez, klucz) == 1550.0, klucz
        assert netto_kart(z, klucz) == 1080.0, klucz
    assert sum(p['netto'] for p in z['trend']['biezacy']) == 1080.0
    # Kubełki klientów liczą się z całej historii — uwaga mówi o wykluczeniach.
    klienci = z['karty']['klienci:liczba_zamowien']
    assert 'wykluczeń' in klienci['uwaga'].lower()
    assert 'wykluczeń' not in bez['karty']['klienci:liczba_zamowien']['uwaga'].lower()
    # Należności: zamówienie 2 (sam buk) wypada razem z saldem 200.
    kubelki = z['karty']['naleznosci:wiek_zamowienia']['kubelki']
    assert sum(k['saldo'] for k in kubelki) == 800.0
    # Lejek liczy wyceny, nie pozycje — ten sam blok z wykluczeniami i bez.
    assert z['lejek'] == bez['lejek']


def _dane_rozszerzone():
    """`_dane_bazowe` plus wszystko, czego tamta fikstura nie ma, a przez co
    wykluczenia trafiają do liczb poza samym okresem: okres poprzedni, ten sam
    okres roku poprzedniego, kanał ręczny z pochodzeniem klienta, klienci
    z pierwszym zamówieniem w okresie, stare saldo „w produkcji" i różne koszty
    dostawy. W KAŻDEJ z tych grup jest zamówienie z samym bukiem, więc liczba
    policzona bez wykluczeń różni się od tej z wykluczeniami.

    Weryfikacja partii E (Z3): na samych `_dane_bazowe` siedem przekazań
    filtra dało się usunąć przy zielonych testach."""
    _dane_bazowe()
    buk = [('100.00', '0.01', 'buk', 'lity', 'A/B', 'towar')]
    nowy_z_bukiem = SalesClient(display_name='A', orders_count=1,
                                lifetime_net=Decimal('100.00'),
                                first_order_at=date(2026, 9, 7))
    nowy_z_debem = SalesClient(display_name='B', orders_count=1,
                               lifetime_net=Decimal('200.00'),
                               first_order_at=date(2026, 9, 6))
    db.session.add_all([nowy_z_bukiem, nowy_z_debem])
    db.session.flush()
    # Kanał ręczny w okresie: segment „Detal" z dębem, „Stały B2B" z samym bukiem.
    _zamowienie(15, date(2026, 9, 6), [('200.00', '0.02', 'dąb', 'lity', 'A/B', 'towar')],
                kanal='personal', pochodzenie='Detal', client_id=nowy_z_debem.id)
    _zamowienie(16, date(2026, 9, 7), buk, kanal='personal', pochodzenie='Stały B2B',
                koszt='25.00', client_id=nowy_z_bukiem.id)
    # Okres poprzedni (11–31.08): sklep z dębem, Allegro z samym bukiem.
    _zamowienie(11, date(2026, 8, 20), [('600.00', '0.05', 'dąb', 'lity', 'A/B', 'towar')])
    _zamowienie(12, date(2026, 8, 21), [('300.00', '0.03', 'buk', 'lity', 'A/B', 'towar')],
                kanal='allegro')
    # Rok poprzedni (trend 2025: styczeń–wrzesień).
    _zamowienie(13, date(2025, 9, 10), [('500.00', '0.05', 'buk', 'lity', 'A/B', 'towar')])
    _zamowienie(14, date(2025, 3, 15), [('200.00', '0.02', 'dąb', 'lity', 'A/B', 'towar')])
    # Stare saldo „w produkcji" (ponad 90 dni przed 21.09.2026).
    _zamowienie(17, date(2026, 3, 2), [('50.00', '0.005', 'buk', 'lity', 'A/B', 'towar')],
                saldo='700.00', status='W produkcji - surowe')
    _zamowienie(18, date(2026, 3, 3), [('40.00', '0.004', 'dąb', 'lity', 'A/B', 'towar')],
                saldo='300.00', status='W produkcji')
    # Nadpłaty (saldo ujemne, liczone z całej historii): jedna z samym bukiem.
    _zamowienie(19, date(2026, 5, 4), [('10.00', '0.001', 'buk', 'lity', 'A/B', 'towar')],
                saldo='-30.00')
    _zamowienie(20, date(2026, 5, 5), [('10.00', '0.001', 'dąb', 'lity', 'A/B', 'towar')],
                saldo='-20.00')
    # Województwa zamówień okresu (kartogram): w każdym jedno z samym bukiem.
    # Sumy okresu się nie zmieniają — dochodzi tylko kolumna zamówienia.
    for bl_id, wojewodztwo in ((1, 'Mazowieckie'), (2, 'Mazowieckie'),
                               (15, 'Śląskie'), (16, 'Śląskie')):
        SalesOrder.query.filter_by(baselinker_order_id=bl_id).one().delivery_state = wojewodztwo
    db.session.commit()


def test_liczby_spoza_okresu_i_kart_bocznych_licza_z_wykluczeniami(app):
    """Każde przekazanie filtra wykluczeń ma tu własną asercję: zmiana % KPI
    (okres poprzedni), trend roku poprzedniego, nowi w okresie, koszt kuriera,
    ostrzeżenie o saldzie, rozbicie kanału ręcznego, udziały kanałów okresu
    bieżącego i poprzedniego we wniosku „Statystyk" i kartogram województw.
    Obok liczby bez wykluczeń — dowód, że dane w ogóle rozróżniają oba
    przypadki. Karty kubełkowe na wymiarze i nadpłaty: test niżej.

    Każdą asercję sprawdzono mutacją: usunięcie jednego przekazania filtra
    (kontrola E: M1–M12, K4, K8–K11) wywraca dokładnie jej wiersz."""
    with app.app_context():
        _dane_rozszerzone()
        uklad = [Instancja(t, KATALOG[t].domyslny_wymiar if KATALOG[t].wymiarowy else None)
                 for t in KATALOG]
        bez = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO))
        z = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO,
                                    wykluczenia={'wood_species': ['buk']},
                                    obecne=OBECNE))

    # KPI okresu: 1850 zł w 6 zamówieniach, bez buku 1280 zł w 4.
    assert (bez['kpi']['netto'], bez['kpi']['zamowienia']) == (1850.0, 6)
    assert (z['kpi']['netto'], z['kpi']['zamowienia']) == (1280.0, 4)
    # Zmiana % wobec okresu poprzedniego, liczonego Z TYMI SAMYMI wykluczeniami:
    # 600 zł w 1 zamówieniu (bez nich 900 zł w 2 — wtedy byłoby +42,2% i +100%).
    assert bez['kpi']['zmiana']['netto'] == pytest.approx(105.6)
    assert z['kpi']['zmiana']['netto'] == pytest.approx(113.3)
    assert z['kpi']['zmiana']['zamowienia'] == pytest.approx(300.0)

    # Trend roku poprzedniego: 200 + 500 (buk) zł, bez buku 200 zł.
    assert sum(p['netto'] for p in bez['trend']['poprzedni']) == 700.0
    assert sum(p['netto'] for p in z['trend']['poprzedni']) == 200.0

    # Nowi w okresie: klient z samym bukiem nie kupił niczego, co zostaje.
    klienci = 'klienci:liczba_zamowien'
    assert bez['karty'][klienci]['nowi_w_okresie'] == 2
    assert z['karty'][klienci]['nowi_w_okresie'] == 1

    # Koszt kuriera, raz na zamówienie: 5 × 10 + 25 zł, bez buku 4 × 10 zł.
    assert bez['dostawa_koszt_kuriera'] == 75.0
    assert z['dostawa_koszt_kuriera'] == 40.0

    # Ostrzeżenie o starym saldzie „w produkcji": bez zamówienia z samym bukiem.
    naleznosci = 'naleznosci:wiek_zamowienia'
    assert bez['karty'][naleznosci]['ostrzezenie'] == {'zamowienia': 2, 'saldo': 1000.0}
    assert z['karty'][naleznosci]['ostrzezenie'] == {'zamowienia': 1, 'saldo': 300.0}

    # Rozbicie kanału ręcznego: „Stały B2B" to sam buk.
    def rozbicie(dane):
        return [(w['etykieta'], w['netto']) for w in dane['kanal_rozbicie']['wiersze']]
    assert rozbicie(bez) == [('Detal', 200.0), ('Stały B2B', 100.0)]
    assert rozbicie(z) == [('Detal', 200.0)]

    # Wniosek o kanale porównuje z udziałem sklepu w okresie poprzednim BEZ
    # buku: 100% (z bukiem sklep miał 600 z 900 zł, czyli 66,7%).
    assert 'wobec 66,7% w poprzednim okresie' in bez['wnioski'][0]['tekst']
    assert 'wobec 100,0% w poprzednim okresie' in z['wnioski'][0]['tekst']
    # …a udział kanału w BIEŻĄCYM okresie też bez buku (kontrola E, K4):
    # sklep 1080 z 1280 zł, a z bukiem 1550 z 1850 zł.
    assert z['wnioski'][0]['tekst'].startswith('Największy kanał to Sklep — 84,4% przychodu')
    assert bez['wnioski'][0]['tekst'].startswith('Największy kanał to Sklep — 83,8% przychodu')

    # Kartogram województw (K10): w każdym województwie jedno zamówienie
    # z samym bukiem wypada.
    def mapa(dane):
        return {o['id']: o['netto'] for o in dane['karty']['wojewodztwo:delivery_state']
                ['mapa']['obszary'] if o['ma_dane']}
    assert mapa(bez) == {'mazowieckie': 1400.0, 'slaskie': 300.0}
    assert mapa(z) == {'mazowieckie': 1000.0, 'slaskie': 200.0}


def test_karty_kubelkowe_na_wymiarze_i_nadplaty_licza_z_wykluczeniami(app):
    """Kontrola E, znalezisko A (K8, K9, K11): karty kubełkowe przełączone na
    wymiar liczą przekrój za okres Z WYKLUCZENIAMI, a nadpłaty (z całej
    historii, ale z zamówień) też. Test typów kafelków bierze tylko wymiary
    domyślne, więc te trzy przekazania filtra nie miały żadnej asercji."""
    with app.app_context():
        _dane_rozszerzone()
        uklad = [Instancja('klienci', 'order_source'),
                 Instancja('naleznosci', 'order_source')]
        bez = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO))
        z = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO,
                                    wykluczenia={'wood_species': ['buk']},
                                    obecne=OBECNE))

    def kawalki(dane, klucz, miara):
        return {w['etykieta']: w[miara] for w in dane['karty'][klucz]['wiersze']}

    # Koło klientów po kanale (K9): netto z pozycji okresu, bez buku.
    assert kawalki(bez, 'klienci:order_source', 'netto') == {'Sklep': 1550.0,
                                                             'Ręczne w BL': 300.0}
    assert kawalki(z, 'klienci:order_source', 'netto') == {'Sklep': 1080.0,
                                                           'Ręczne w BL': 200.0}
    # Należności po kanale (K11): saldo zamówień okresu; zamówienie 2
    # (sam buk, saldo 200 zł) wypada, mieszane 4 zostaje z całym saldem.
    assert kawalki(bez, 'naleznosci:order_source', 'liczba') == {'Sklep': 1000.0}
    assert kawalki(z, 'naleznosci:order_source', 'liczba') == {'Sklep': 800.0}
    # Nadpłaty (K8): zamówienie 19 (sam buk, -30 zł) wypada.
    assert bez['karty']['naleznosci:order_source']['nadplaty'] == {'zamowienia': 2,
                                                                   'saldo': 50.0}
    assert z['karty']['naleznosci:order_source']['nadplaty'] == {'zamowienia': 1,
                                                                 'saldo': 20.0}


def test_najwyzsze_srednie_zamowienie_liczy_z_wykluczeniami(app):
    """Weryfikacja E8 (Z2, H5): wiersz „Najwyższe śr. zamówienie" karty
    opiekunów liczy się z tym samym filtrem, co karta. Bez przekazania filtra
    przy odznaczonym buku wygrywałby opiekun, którego średnia stoi na buku
    (na produkcji we wrześniu 2026 zmieniało to zwycięzcę tego wiersza).

    Bartek ma jedno zamówienie: buk za 2000 zł i dąb za 100 zł. Bez buku
    zostaje mu 100 zł, a Annie 1080 zł w trzech zamówieniach, czyli 360 zł."""
    with app.app_context():
        _dane_bazowe()
        _zamowienie(26, date(2026, 9, 8),
                    [('2000.00', '0.20', 'buk', 'lity', 'A/B', 'towar'),
                     ('100.00', '0.01', 'dąb', 'lity', 'A/B', 'towar')],
                    opiekun='Bartek')
        db.session.commit()
        uklad = [Instancja('opiekun', 'caretaker')]
        bez = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO))
        z = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO,
                                    wykluczenia={'wood_species': ['buk']},
                                    obecne=OBECNE))

    klucz = 'opiekun:caretaker'
    assert bez['karty'][klucz]['najlepszy'] == {'etykieta': 'Bartek', 'srednie': 2100.0}
    assert z['karty'][klucz]['najlepszy'] == {'etykieta': 'Anna', 'srednie': 360.0}


def test_druga_seria_segmentu_liczy_sie_z_wykluczeniami_w_kazdym_bloku(app):
    """Weryfikacja E8 (Z2, H26–H30): segment porównawczy dostaje przecięcie
    swojego filtra z wykluczeniami nie tylko w KPI
    (`test_segment_przecina_sie_z_wykluczeniami`), ale w KAŻDYM bloku
    drugiej serii: trendzie, kartach i ich ogonach, kartogramie, koszcie
    kuriera i rozbiciu kanału ręcznego. Usunięcie któregokolwiek z tych
    przekazań zmieniało liczby na produkcji, a testy zostawały zielone.

    Segment „opiekun: Anna" obejmuje wszystkie zamówienia fikstury, więc bez
    wykluczeń jego seria to liczby z bukiem, a z wykluczeniami — bez buku.
    Każda asercja ma obok wariant bez wykluczeń: dowód, że dane rozróżniają
    oba przypadki."""
    with app.app_context():
        _dane_rozszerzone()
        # Pomorskie: zamówienie mieszane. Karta dostawy po województwie ma
        # przez nie cztery wiersze przy limicie trzech, czyli ogon.
        _zamowienie(30, date(2026, 9, 8),
                    [('500.00', '0.05', 'dąb', 'lity', 'A/B', 'towar'),
                     ('250.00', '0.02', 'buk', 'lity', 'A/B', 'towar')],
                    wojewodztwo='Pomorskie')
        # „Detal" z samym bukiem. Bez niego wiersz „Detal" rozbicia kanału
        # ręcznego byłby taki sam z wykluczeniami i bez nich.
        _zamowienie(31, date(2026, 9, 9), [('120.00', '0.01', 'buk', 'lity', 'A/B', 'towar')],
                    kanal='personal', pochodzenie='Detal', wojewodztwo='Śląskie')
        db.session.commit()
        uklad = [Instancja('kpi', None), Instancja('kanal', 'order_source'),
                 Instancja('wojewodztwo', 'delivery_state'),
                 Instancja('dostawa', 'delivery_state')]
        segment = {'caretaker': ['Anna']}
        bez = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO, porownanie=segment))
        z = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO, porownanie=segment,
                                    wykluczenia={'wood_species': ['buk']},
                                    obecne=OBECNE))
    seg_bez, seg_z = bez['porownanie'], z['porownanie']

    # KPI okresu: 2720 zł z bukiem, 1780 zł bez niego.
    assert (seg_bez['kpi']['netto'], seg_z['kpi']['netto']) == (2720.0, 1780.0)

    # Trend (H29), styczeń–21 września 2026: 3730 zł, bez buku 2430 zł.
    assert sum(p['netto'] for p in seg_bez['trend']) == 3730.0
    assert sum(p['netto'] for p in seg_z['trend']) == 2430.0

    # Karty (H30), w układzie wierszy karty bazowej. Kanały: Sklep, Ręczne w BL.
    def netto(wiersze):
        return [w['netto'] for w in wiersze]
    assert netto(seg_bez['karty']['kanal:order_source']) == [2300.0, 420.0]
    assert netto(seg_z['karty']['kanal:order_source']) == [1580.0, 200.0]
    # Dostawa po województwie: Mazowieckie, Pomorskie, „Pozostałe (2)"
    # i rozwinięty ogon: Śląskie, (brak).
    dostawa = 'dostawa:delivery_state'
    assert [w['etykieta'] for w in z['karty'][dostawa]['wiersze']] == [
        'Mazowieckie', 'Pomorskie', 'Pozostałe (2)']
    assert [w['etykieta'] for w in z['karty'][dostawa]['ogon']] == ['Śląskie', '(brak)']
    assert netto(seg_bez['karty'][dostawa]) == [1400.0, 750.0, 570.0]
    assert netto(seg_z['karty'][dostawa]) == [1000.0, 500.0, 280.0]
    assert netto(seg_bez['ogony'][dostawa]) == [420.0, 150.0]
    assert netto(seg_z['ogony'][dostawa]) == [200.0, 80.0]

    # Kartogram (H27): druga liczba w dymku, w układzie obszarów mapy bazowej.
    def mapa(dane):
        obszary = dane['karty']['wojewodztwo:delivery_state']['mapa']['obszary']
        return {o['id']: s['netto'] for o, s in
                zip(obszary, dane['porownanie']['mapa']['obszary']) if s['netto']}
    assert mapa(bez) == {'mazowieckie': 1400.0, 'pomorskie': 750.0, 'slaskie': 420.0}
    assert mapa(z) == {'mazowieckie': 1000.0, 'pomorskie': 500.0, 'slaskie': 200.0}

    # Koszt kuriera (H28), raz na zamówienie: 7 × 10 + 25 zł, a bez buku
    # zostaje pięć zamówień po 10 zł.
    assert seg_bez['dostawa_koszt_kuriera'] == 95.0
    assert seg_z['dostawa_koszt_kuriera'] == 50.0

    # Rozbicie kanału ręcznego (H26), w układzie wierszy rozbicia bazowego.
    assert netto(seg_bez['kanal_rozbicie']) == [320.0, 100.0]
    assert netto(seg_z['kanal_rozbicie']) == [200.0]


# --- wykończenie: czwarta grupa (partia E, punkt E8) ---------------------------

def _dane_wykonczen():
    """Wrzesień: zamówienie surowe, lakierowane, mieszane (lakierowany buk
    + surowy dąb) i pozycja bez wykończenia (NULL — ma zostać zawsze)."""
    _zamowienie(21, date(2026, 9, 2), [('1000.00', '0.10', 'dąb', 'lity', 'A/B', 'towar')],
                saldo='100.00')
    _zamowienie(22, date(2026, 9, 3),
                [('300.00', '0.03', 'dąb', 'lity', 'A/B', 'towar', 'lakierowany')],
                saldo='200.00')
    _zamowienie(23, date(2026, 9, 4),
                [('200.00', '0.02', 'buk', 'lity', 'A/B', 'towar', 'lakierowany'),
                 ('100.00', '0.01', 'dąb', 'lity', 'A/B', 'towar')],
                saldo='300.00')
    _zamowienie(24, date(2026, 9, 5),
                [('80.00', '0.01', 'dąb', 'lity', 'A/B', 'towar', None)], saldo='50.00')
    _zamowienie(25, date(2026, 9, 6),
                [('150.00', '0.01', 'jesion', 'lity', 'A/B', 'towar', 'olejowany')])
    db.session.commit()


# --- kolor kawałka koła idzie za encją (decyzja z 24.09.2026) ---------------
#
# Kolor wartości nie zmienia się przy ŻADNEJ kombinacji wykluczeń. Odniesieniem
# jest ta sama karta bez wykluczeń: jej czołówka (tyle wartości, ile paleta ma
# kolorów kategorii, w kolejności kawałków i rozpisanego ogona) dostaje stałe
# kolory kategorii, a każda inna wartość i „Pozostałe (N)" — zawsze ten sam
# kolor neutralny. Zastępuje przydział z zapasem („wolne kolory" dla wartości
# z ogona, awaryjnie kolor „Pozostałe"), który przemalowywał kawałki, gdy
# kliknięcie usuwało albo przywracało kawałek „Pozostałe" (kontrola ostatnich
# poprawek, WAŻNE 1). Nazwy opiekunów i statusów w danych są fikcyjne.

KAT, NEU = KOLORY_KATEGORII, INDEKS_NEUTRALNY


def _stany_osiagalne(obecne):
    """Każda kombinacja wykluczeń, którą da się wyklikać: w każdym polu
    dowolny podzbiór wartości, byle nie wszystkie naraz (interfejs blokuje
    ostatnie pole wyboru, a `parsuj_wykluczenia` odrzuca taki stan).
    Pierwszy stan to pulpit bez wykluczeń."""
    pola = [(nazwa, wartosci) for nazwa, wartosci in obecne.items() if wartosci]
    podzbiory = [[list(c) for n in range(len(wartosci))
                  for c in itertools.combinations(wartosci, n)]
                 for _, wartosci in pola]
    return [{nazwa: wybor for (nazwa, _), wybor in zip(pola, kombinacja) if wybor}
            for kombinacja in itertools.product(*podzbiory)]


def _karty_we_wszystkich_stanach(uklad):
    """{klucz karty: [karta w każdym stanie osiągalnym]}; pierwsza bez wykluczeń.

    Pola wyboru buduje ta sama funkcja co pasek pulpitu (`wartosci_wykluczen`),
    więc stany to dokładnie te, które da się wyklikać na tych danych."""
    obecne = wartosci_wykluczen()
    stany = _stany_osiagalne(obecne)
    assert stany[0] == {}
    wyniki = {i.klucz: [] for i in uklad}
    for wykluczenia in stany:
        karty = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO,
                                        wykluczenia=wykluczenia or None,
                                        obecne=obecne))['karty']
        for klucz, lista in wyniki.items():
            lista.append(karty[klucz])
    return wyniki


def _kolory_za_encja(karty):
    """Reguła na jednej karcie we wszystkich stanach; zwraca {etykieta: indeks}
    każdej wartości, którą gdzieś widać jako osobny kawałek.

    - wartość ma JEDEN kolor we wszystkich stanach, w których ją widać;
    - na jednym kole żadne dwa NIENEUTRALNE kawałki nie dzielą koloru;
    - „Pozostałe (N)" i wiersze rozpisanego ogona (legenda) są neutralne."""
    kolory = {}
    for karta in karty:
        nieneutralne = [w['indeks_koloru'] for w in karta['wiersze']
                        if w['indeks_koloru'] != NEU]
        assert len(set(nieneutralne)) == len(nieneutralne), karta['wiersze']
        for w in karta['wiersze']:
            if w['zbiorczy']:
                assert w['indeks_koloru'] == NEU, w
            else:
                kolory.setdefault(w['etykieta'], set()).add(w['indeks_koloru'])
        assert all(w['indeks_koloru'] == NEU for w in karta['ogon']), karta['ogon']
    assert {e: k for e, k in kolory.items() if len(k) > 1} == {}, kolory
    return {e: k.pop() for e, k in kolory.items()}


def _neutralne(karta):
    """Etykiety NAZWANYCH kawałków w kolorze neutralnym (bez „Pozostałe")."""
    return [w['etykieta'] for w in karta['wiersze']
            if not w['zbiorczy'] and w['indeks_koloru'] == NEU]


def test_paleta_kola_ma_neutralny_i_cztery_kolory_kategorii():
    """Neutralny kolor nie jest kolorem żadnej kategorii, a kategorii jest
    tyle, ile palety zostaje bez niego (analiza.js, `KOLORY_PIERSCIENIA`;
    zgodność z przeglądarką pilnuje test_analiza_widok.py)."""
    assert NEU not in KAT
    assert sorted(KAT + (NEU,)) == list(range(len(KAT) + 1))
    assert len(KAT) == 4


def test_kolor_kawalka_pierscienia_wykonczen_idzie_za_encja(app):
    """Karta wykończeń (limit 3: dwa kawałki i „Pozostałe"). Bez wykluczeń:
    surowy 3000, lakierowany 2000, Pozostałe (4) = olejowany 1200, woskowany
    800, (brak) 500, bejcowany 300. Czołówka odniesienia to cztery pierwsze
    wartości — także dwie z ogona; (brak) i bejcowany są spoza niej.

    Przed decyzją z 24.09.2026 wartość spoza wolnych kolorów brała awaryjnie
    kolor „Pozostałe" i oddawała go, gdy ten kawałek wracał na koło."""
    with app.app_context():
        for bl, (netto, gatunek, wykonczenie) in enumerate(
                [('3000.00', 'dąb', 'surowy'), ('2000.00', 'buk', 'lakierowany'),
                 ('1200.00', 'dąb', 'olejowany'), ('800.00', 'buk', 'woskowany'),
                 ('500.00', 'dąb', None), ('300.00', 'buk', 'bejcowany')], start=61):
            _zamowienie(bl, date(2026, 9, 3),
                        [(netto, '0.10', gatunek, 'lity', 'A/B', 'towar', wykonczenie)])
        db.session.commit()
        karty = _karty_we_wszystkich_stanach(
            [Instancja('wykonczenie', 'finish_state')])['wykonczenie:finish_state']

    # 3 stany gatunku × 31 stanów wykończenia (pięć wartości z pola wyboru).
    assert len(karty) == 93
    bez = karty[0]
    assert [w['etykieta'] for w in bez['wiersze']] == ['surowy', 'lakierowany', 'Pozostałe (4)']
    assert [w['indeks_koloru'] for w in bez['wiersze']] == [KAT[0], KAT[1], NEU]
    assert [w['indeks_koloru'] for w in bez['ogon']] == [NEU] * 4

    assert _kolory_za_encja(karty) == {
        'surowy': KAT[0], 'lakierowany': KAT[1], 'olejowany': KAT[2], 'woskowany': KAT[3],
        '(brak)': NEU, 'bejcowany': NEU}
    # Stan, o który chodziło: dwie wartości spoza czołówki obok siebie, obie
    # neutralne (bez surowego, lakierowanego i olejowanego).
    assert max(len(_neutralne(k)) for k in karty) == 2


def test_kolor_kawalka_kola_klientow_idzie_za_encja(app):
    """Koło „Klienci według" (limit 4: trzy kawałki i „Pozostałe") na trzech
    wymiarach: kubełki, opiekun i województwo — dla wszystkich kombinacji
    wykluczeń gatunku i wykończenia.

    Opiekun bez wykluczeń: A 5000, B 4000, C 3000, Pozostałe (5) = D 2000,
    E 1500, F 1000, H 700, G 500 — czołówka A, B, C i D. Województwo:
    Mazowieckie 8000, Pomorskie 4000, Śląskie 3000, Pozostałe (3) = Łódzkie
    1500, (brak) 700, Opolskie 500. Kubełków są cztery w stałej kolejności,
    więc całe koło to czołówka."""
    with app.app_context():
        for i, (liczba, netto) in enumerate([(1, '700.00'), (2, '900.00'),
                                             (5, '400.00'), (12, '1500.00')]):
            db.session.add(SalesClient(display_name=f'Klient {i}', orders_count=liczba,
                                       lifetime_net=Decimal(netto)))
        for bl, (opiekun, netto, gatunek, wykonczenie, wojewodztwo) in enumerate(
                [('Opiekun A', '5000.00', 'dąb', 'surowy', 'Mazowieckie'),
                 ('Opiekun B', '4000.00', 'buk', 'lakierowany', 'Pomorskie'),
                 ('Opiekun C', '3000.00', 'dąb', 'surowy', 'Mazowieckie'),
                 ('Opiekun D', '2000.00', 'jesion', 'lakierowany', 'Śląskie'),
                 ('Opiekun E', '1500.00', 'dąb', 'surowy', 'Łódzkie'),
                 ('Opiekun F', '1000.00', 'buk', 'surowy', 'Śląskie'),
                 ('Opiekun G', '500.00', 'jesion', 'surowy', 'Opolskie'),
                 ('Opiekun H', '700.00', 'buk', 'surowy', None)], start=71):
            _zamowienie(bl, date(2026, 9, 3),
                        [(netto, '0.10', gatunek, 'lity', 'A/B', 'towar', wykonczenie)],
                        opiekun=opiekun, wojewodztwo=wojewodztwo)
        db.session.commit()
        uklad = [Instancja('klienci', 'liczba_zamowien'), Instancja('klienci', 'caretaker'),
                 Instancja('klienci', 'delivery_state')]
        wyniki = _karty_we_wszystkich_stanach(uklad)

    kubelki, opiekun, wojewodztwo = (wyniki[i.klucz] for i in uklad)
    # 7 stanów gatunku (trzy wartości) × 3 stany wykończenia (dwie).
    assert len(opiekun) == 21

    etykiety_kubelkow = [w['etykieta'] for w in kubelki[0]['wiersze']]
    assert len(etykiety_kubelkow) == 4
    assert _kolory_za_encja(kubelki) == dict(zip(etykiety_kubelkow, KAT))

    assert [w['indeks_koloru'] for w in opiekun[0]['wiersze']] == [KAT[0], KAT[1], KAT[2], NEU]
    assert _kolory_za_encja(opiekun) == {
        'Opiekun A': KAT[0], 'Opiekun B': KAT[1], 'Opiekun C': KAT[2], 'Opiekun D': KAT[3],
        'Opiekun E': NEU, 'Opiekun F': NEU, 'Opiekun G': NEU, 'Opiekun H': NEU}

    assert _kolory_za_encja(wojewodztwo) == {
        'Mazowieckie': KAT[0], 'Pomorskie': KAT[1], 'Śląskie': KAT[2], 'Łódzkie': KAT[3],
        '(brak)': NEU, 'Opolskie': NEU}
    # Bez dębu na kole zostają Pomorskie, Śląskie, (brak) i Opolskie —
    # dwa neutralne kawałki obok siebie, każdy z własną etykietą.
    assert max(len(_neutralne(k)) for k in wojewodztwo) == 2

    # Przejście, którego poprzednie testy nie widziały (kontrola ostatnich
    # poprawek, WAŻNE 1): kliknięcie usuwa kawałek „Pozostałe", a wartość
    # spoza czołówki zostaje na kole. Bez dębu: B, D, F i Pozostałe (H, G);
    # bez dębu i jesionu: B, F i H, już bez „Pozostałe". F jest neutralny
    # w obu stanach, B trzyma swój kolor.
    def stan(karta):
        return {w['etykieta']: w['indeks_koloru'] for w in karta['wiersze']}
    z_pozostalymi = [stan(k) for k in opiekun
                     if set(stan(k)) == {'Opiekun B', 'Opiekun D', 'Opiekun F', 'Pozostałe (2)'}]
    bez_pozostalych = [stan(k) for k in opiekun
                       if set(stan(k)) == {'Opiekun B', 'Opiekun F', 'Opiekun H'}]
    assert z_pozostalymi and bez_pozostalych
    for wiersze in z_pozostalymi + bez_pozostalych:
        assert wiersze['Opiekun F'] == NEU
        assert wiersze['Opiekun B'] == KAT[1]


def test_kolor_kawalka_karty_z_dlugim_ogonem_idzie_za_encja(app):
    """Karta wykończeń przestawiona na status zamówienia — osiem statusów
    przy limicie trzech wierszy, więc ogon jest dłuższy niż kolory palety.
    Bez wykluczeń: Nowe 5000, W realizacji 4000, Pozostałe (6); czołówka to
    Nowe, W realizacji, Do wysyłki i Wysłane, cztery pozostałe są neutralne
    w każdym stanie."""
    statusy = [('Nowe', '5000.00', 'dąb', 'surowy'),
               ('W realizacji', '4000.00', 'buk', 'surowy'),
               ('Do wysyłki', '3000.00', 'jesion', 'surowy'),
               ('Wysłane', '2500.00', 'dąb', 'surowy'),
               ('Odebrane', '2000.00', 'buk', 'lakierowany'),
               ('Reklamacja', '1500.00', 'jesion', 'surowy'),
               ('Wstrzymane', '1000.00', 'buk', 'surowy'),
               ('Do odbioru', '500.00', 'dąb', 'lakierowany')]
    with app.app_context():
        for bl, (status, netto, gatunek, wykonczenie) in enumerate(statusy, start=81):
            _zamowienie(bl, date(2026, 9, 3),
                        [(netto, '0.10', gatunek, 'lity', 'A/B', 'towar', wykonczenie)],
                        status=status)
        db.session.commit()
        karty = _karty_we_wszystkich_stanach(
            [Instancja('wykonczenie', 'current_status')])['wykonczenie:current_status']

    assert len(karty) == 21
    assert [w['etykieta'] for w in karty[0]['wiersze']] == ['Nowe', 'W realizacji',
                                                            'Pozostałe (6)']
    oczekiwane = {nazwa: (KAT[i] if i < len(KAT) else NEU)
                  for i, (nazwa, *_) in enumerate(statusy)}
    kolory = _kolory_za_encja(karty)
    # Każda wartość, także każda spoza czołówki, jest gdzieś widoczna jako
    # osobny kawałek — test naprawdę sprawdza jej kolor.
    assert kolory == oczekiwane
    assert max(len(_neutralne(k)) for k in karty) >= 2


def test_odznaczony_lakierowany_wycina_tylko_pozycje_lakierowane(app):
    """Ta sama semantyka co E4: pozycja bez wykończenia (NULL) zostaje,
    zamówienie z samymi lakierowanymi wypada z liczby zamówień i salda,
    zamówienie mieszane zostaje z samą pozycją surową."""
    with app.app_context():
        _dane_wykonczen()
        wykonczenia = {'finish_state': ['surowy', 'lakierowany', 'olejowany']}
        filtr = filtr_z_wykluczen({'finish_state': ['lakierowany']}, wykonczenia)
        bez = kpi(OD, DO)
        z = kpi(OD, DO, filtr=filtr)

    assert filtr == {'finish_state': ['surowy', 'olejowany', '']}
    # 1000 + 300 + 200 + 100 + 80 + 150 = 1830; bez lakierowanych 1830 - 500.
    assert bez['netto'] == Decimal('1830.00')
    assert z['netto'] == Decimal('1330.00')
    assert (bez['zamowienia'], z['zamowienia']) == (5, 4)
    assert (bez['saldo'], z['saldo']) == (Decimal('650.00'), Decimal('450.00'))


def test_wykonczenie_laczy_sie_koniunkcja_z_gatunkiem(app):
    """Odznaczone „buk" i „olejowany": wypada buk (lakierowany, 200 zł)
    i jesion olejowany (150 zł) — grupy łączą się koniunkcją."""
    with app.app_context():
        _dane_wykonczen()
        obecne = dict(OBECNE, finish_state=['surowy', 'lakierowany', 'olejowany'])
        filtr = filtr_z_wykluczen({'wood_species': ['buk'],
                                   'finish_state': ['olejowany']}, obecne)
        wynik = kpi(OD, DO, filtr=filtr)
    assert wynik['netto'] == Decimal('1480.00')
    assert wynik['zamowienia'] == 4


def test_karta_wykonczen_nie_ma_kawalka_lakierowanego(client, app):
    """Kafelek „Sprzedaż netto według: Wykończenie" przy odznaczonym
    „lakierowany" liczy się bez tych pozycji — kawałka nie ma wcale,
    a „(brak)" (pozycja bez wykończenia) zostaje."""
    with app.app_context():
        _dane_wykonczen()
    tekst = _wyklucz(finish_state=['lakierowany'])
    z = client.get(f'/reports/api/kafelek?typ=wykonczenie&wymiar=finish_state'
                   f'&{OKRES}&wyklucz={tekst}').get_json()['dane']
    bez = client.get(f'/reports/api/kafelek?typ=wykonczenie&wymiar=finish_state'
                     f'&{OKRES}').get_json()['dane']
    klucz = 'wykonczenie:finish_state'

    def wiersze(dane):
        karta = dane['karty'][klucz]
        return {w['etykieta']: w['netto'] for w in karta['wiersze'] + karta['ogon']
                if not w['zbiorczy']}

    assert 'lakierowany' in wiersze(bez)
    assert 'lakierowany' not in wiersze(z)
    assert sum(wiersze(z).values()) == 1330.0
    assert z['wykluczenia']['opis'] == 'Bez: lakierowany'


def test_cena_za_m3_z_wykonczeniem_liczy_z_wykluczeniami(app):
    """Weryfikacja E8 (Z1 i H6): „Cena za m³ z wykończeniem" pod pierścieniem
    liczy się z tym samym filtrem, co karta, i tylko z wykończeń z objętością.

    Na produkcji odznaczenie „lakierowany" zabierało z tej strony prawdziwą
    objętość, a usługi bez wykończenia (netto bez m³) zostawały, bo pusta
    wartość zostaje zawsze: +2 027,4% zamiast +153,5% (wrzesień 2025).

    Surowy 1100 zł / 0,11 m³ i lakierowany 500 zł / 0,05 m³ to po
    10 000 zł/m³, olejowany 150 zł / 0,01 m³ to 15 000 zł/m³. „(brak)" —
    towar za 80 zł i usługa za 500 zł bez objętości — się nie liczy."""
    with app.app_context():
        _dane_wykonczen()
        _zamowienie(26, date(2026, 9, 7), [('500.00', '0', None, None, None, 'usługa', None)])
        db.session.commit()
        obecne = dict(OBECNE, finish_state=['surowy', 'lakierowany', 'olejowany'])
        uklad = [Instancja('wykonczenie', 'finish_state')]
        bez = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO))
        z = do_json(dane_dashboardu(OD, DO, uklad, na_dzien=DO,
                                    wykluczenia={'finish_state': ['lakierowany']},
                                    obecne=obecne))

    klucz = 'wykonczenie:finish_state'
    # Lakierowany i olejowany razem: 650 zł / 0,06 m³, czyli o 8,3% drożej.
    assert bez['karty'][klucz]['roznica_do_surowego'] == 8.3
    # Bez lakierowanego zostaje sam olejowany: o 50,0% drożej.
    assert z['karty'][klucz]['roznica_do_surowego'] == 50.0


def test_zdanie_przy_tytule_nazywa_pola_etykieta_z_rejestru(client, app):
    """Weryfikacja E8 (Z2, E8z): zdanie pod tytułem wymienia pola, w których
    coś odznaczono, etykietą z rejestru. Pole wpisane w zdanie na sztywno
    („Gatunek") przechodziło przez wszystkie testy — tamten test pilnuje
    tylko zakazanych wyliczeń i komunikatu walidacji."""
    with app.app_context():
        _dane_wykonczen()

    def zdanie(**pola):
        return client.get(f'/reports/api/analytics?{OKRES}&wyklucz={_wyklucz(**pola)}') \
                     .get_json()['wykluczenia']['zdanie']

    samo_wykonczenie = zdanie(finish_state=['lakierowany'])
    assert POLA['finish_state'].etykieta in samo_wykonczenie
    for nazwa in ('wood_species', 'technology', 'wood_class'):
        assert POLA[nazwa].etykieta not in samo_wykonczenie, nazwa
    gatunek_i_wykonczenie = zdanie(wood_species=['buk'], finish_state=['lakierowany'])
    for nazwa in ('wood_species', 'finish_state'):
        assert POLA[nazwa].etykieta in gatunek_i_wykonczenie, nazwa


def test_zdanie_przy_tytule_nie_obiecuje_przy_kilku_grupach_ze_puste_pole_chroni(client, app):
    """Porządki końcowe, punkt 3a (weryfikacja E8, D1/Z3). Puste pole chroni
    pozycję TYLKO przed wykluczeniem z TEGO pola. Pozycja z pustym gatunkiem,
    ale lakierowana, przy odznaczonych „buk" i „lakierowany" wypada — więc
    zdanie „Pozycje z pustym polem Gatunek albo Wykończenie liczą się zawsze"
    kłamało (na produkcji 4 pozycje, 13 453,08 zł).

    Przy jednej grupie obietnica jest prawdziwa i zostaje. Przy kilku zdanie
    mówi, co naprawdę się dzieje: wypada tylko odznaczona wartość, a puste
    pole samo pozycji nie wyklucza."""
    with app.app_context():
        _dane_wykonczen()

    def zdanie(**pola):
        return client.get(f'/reports/api/analytics?{OKRES}&wyklucz={_wyklucz(**pola)}')                      .get_json()['wykluczenia']['zdanie']

    jedna = zdanie(finish_state=['lakierowany'])
    assert 'liczą się zawsze' in jedna

    for pola in ({'wood_species': ['buk'], 'finish_state': ['lakierowany']},
                 {'wood_species': ['jesion'], 'finish_state': ['surowy']}):
        kilka = zdanie(**pola)
        assert 'liczą się zawsze' not in kilka, pola
        assert 'tylko przez odznaczoną wartość' in kilka, pola
        assert 'nie wyklucza' in kilka, pola
        for nazwa in pola:
            assert POLA[nazwa].etykieta in kilka, nazwa


def test_zdanie_przy_tytule_wylicza_trzy_grupy_przecinkami(client, app):
    """Przy trzech i więcej grupach pola wylicza się przecinkami, z „albo"
    tylko przed ostatnim — samo „albo" dawało przy czterech grupach
    „Gatunek albo Technologia albo Klasa albo Wykończenie" (weryfikacja E8)."""
    with app.app_context():
        _dane_bazowe()
    tekst = _wyklucz(wood_species=['buk'], technology=['mikrowczep'], wood_class=['B/B'])
    zdanie = client.get(f'/reports/api/analytics?{OKRES}&wyklucz={tekst}')                    .get_json()['wykluczenia']['zdanie']
    gatunek, technologia, klasa = (POLA[n].etykieta for n in
                                   ('wood_species', 'technology', 'wood_class'))
    assert f'puste pole {gatunek}, {technologia} albo {klasa} (np. u usług)' in zdanie


def test_strona_rysuje_grupe_wykonczenia_po_klasie(client, app):
    with app.app_context():
        _dane_wykonczen()
    tekst = _wyklucz(finish_state=['lakierowany'])
    strona = client.get(f'/reports/analiza?{OKRES}&wyklucz={tekst}').get_data(as_text=True)
    # Czwarta grupa, etykieta z rejestru, po klasie.
    blok = strona.split('id="an-wykluczenia"')[1].split('id="an-wyk-podpowiedz"')[0]
    grupy = [czesc.split('"')[0] for czesc in blok.split('data-pole-wykluczen="')[1:]]
    assert grupy == list(POLA_WYKLUCZEN)
    assert blok.index('>Klasa<') < blok.index('>Wykończenie<')
    lakierowany = strona.split('value="lakierowany"')[1].split('>')[0]
    surowy = strona.split('value="surowy"')[1].split('>')[0]
    assert 'checked' not in lakierowany
    assert 'checked' in surowy
    assert 'Bez: lakierowany' in strona


@pytest.mark.parametrize('zly', ['finish_state:bejcowany',
                                 'finish_state:surowy|lakierowany|olejowany'])
def test_zle_wykonczenie_na_api_to_400(client, app, zly):
    with app.app_context():
        _dane_wykonczen()
    odp = client.get(f'/reports/api/analytics?{OKRES}&wyklucz={zly}')
    assert odp.status_code == 400
    assert odp.get_json()['error'] == 'zle_wykluczenia'


# --- lista wartości w popoverze segmentu (partia E8, punkt 4f) ------------------

def test_lista_wartosci_filtra_liczy_z_wykluczeniami(client, app):
    """Weryfikacja partii E: `/api/wartosci-wymiaru` (lista w popoverze
    „Dodaj porównanie") liczyła zamówienia bez wykluczeń, więc przy
    odznaczonym buku podpowiadała kanał, w którym po wykluczeniu nie zostaje
    nic, i liczniki niezgodne z pulpitem obok. Liczy tak samo jak karty:
    zamówienia z co najmniej jedną niewykluczoną pozycją."""
    with app.app_context():
        _dane_bazowe()
        _zamowienie(9, date(2026, 9, 6), [('90.00', '0.01', 'buk', 'lity', 'A/B', 'towar')],
                    kanal='personal')
        db.session.commit()
    adres = f'/reports/api/wartosci-wymiaru?wymiar=order_source&{OKRES}'

    def liczniki(odpowiedz):
        return {w['wartosc']: w['zamowienia'] for w in odpowiedz.get_json()['wartosci']}

    assert liczniki(client.get(adres)) == {'shop': 4, 'personal': 1}
    z = client.get(f'{adres}&wyklucz={_wyklucz(wood_species=["buk"])}')
    # Zamówienie 2 (sam buk) i 9 (sam buk, kanał ręczny) wypadają.
    assert liczniki(z) == {'shop': 3}
    zly = client.get(f'{adres}&wyklucz=wood_species:grab')
    assert zly.status_code == 400
    assert zly.get_json()['error'] == 'zle_wykluczenia'


def test_popover_segmentu_niesie_wykluczenia_do_listy_wartosci():
    """Pulpit podaje popoverowi bieżące wykluczenia, a popover dokleja je do
    adresu listy wartości. Eksplorator i Arkusz wykluczeń nie mają — adres
    zostaje wtedy bez parametru."""
    assert 'wyklucz: stan.wyklucz' in _funkcja(_js(), 'podepnijSegmenty')
    with open(os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'filtr.js'),
              encoding='utf-8') as plik:
        filtr_js = plik.read()
    assert "(opcje.wyklucz ? '&wyklucz=' + encodeURIComponent(opcje.wyklucz) : '')" in filtr_js


# --- analiza.js: stan w adresie, opóźnienie, spóźnione odpowiedzi -------------

SCIEZKA_JS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'analiza.js')


def _js():
    return open(SCIEZKA_JS, encoding='utf-8').read()


def _funkcja(js, nazwa):
    """Ciało funkcji na poziomie modułu (wcięcie dwóch spacji)."""
    return js.split('function ' + nazwa)[1].split('\n  }\n')[0]


def test_js_opoznia_zadanie_po_kliknieciu_pola():
    """Szybkie kliknięcie trzech pól ma dać JEDNO żądanie, nie trzy."""
    js = _js()
    assert 'var OPOZNIENIE_WYKLUCZEN = 250;' in js
    cialo = _funkcja(js, 'podepnijWykluczenia')
    assert 'window.clearTimeout(czasWykluczen)' in cialo
    assert 'window.setTimeout(' in cialo and 'OPOZNIENIE_WYKLUCZEN' in cialo
    # Dane przeładowują się bez przeładowania strony — tą samą drogą co okres.
    assert 'ustawParametry({ wyklucz: tekst })' in cialo


def test_js_spozniona_odpowiedz_nie_nadpisuje_nowszej():
    cialo = _funkcja(_js(), 'zaladuj')
    assert 'var numer = numerLadowania;' in cialo
    # Sprawdzenie PRZED rysowaniem i przed pokazaniem błędu.
    assert cialo.count('numer !== numerLadowania') >= 3


def test_js_niesie_wykluczenia_w_adresie_i_do_kafelka():
    js = _js()
    assert "parametry.set('wyklucz', stan.wyklucz)" in _funkcja(js, 'parametryStanu')
    assert "parametry.set('wyklucz', stan.wyklucz)" in _funkcja(js, 'adresKafelka')
    assert "korzen.getAttribute('data-wyklucz')" in _funkcja(js, 'odczytajStanZeStrony')
    assert "parametry.get('wyklucz')" in _funkcja(js, 'odczytajStanZAdresu')


def test_js_sklada_parametr_z_czlonow_zakodowanych_przez_serwer():
    """Jedno źródło postaci adresu: kod wartości robi serwer (filters.zapisz_filtr),
    przeglądarka tylko skleja — i sortuje pola, tak jak zapisz_filtr."""
    cialo = _funkcja(_js(), 'tekstWykluczen')
    assert "getAttribute('data-czlon')" in cialo
    assert 'encodeURIComponent' not in cialo
    assert '.sort()' in cialo


def test_js_blokuje_ostatnie_zaznaczone_pole_grupy():
    cialo = _funkcja(_js(), 'odswiezBlokadyWykluczen')
    assert 'zaznaczone.length === 1 && p.checked' in cialo
    assert 'p.disabled = zablokowane' in cialo


def test_js_nie_uzywa_innerhtml():
    assert '.innerHTML' not in _js()


def test_stopki_w_js_dostaja_filtr_z_serwera():
    js = _js()
    assert "if (filtrWyjsc) { parametry.set('filtr', filtrWyjsc); }" in js
    assert "odswiezStopki(wezel, wykluczenia.filtr || '')" in js
