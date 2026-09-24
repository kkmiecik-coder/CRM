# -*- coding: utf-8 -*-
"""Payload dashboardu składany z UKŁADU użytkownika, nie ze stałej listy kart.

Fikstury (SQLite w pamięci, komplet modeli w rejestrze mapperów) są przepisane
z tests/test_analiza_api.py — patrz tamten docstring po uzasadnienie bloku
importów „rejestr mapperów" i szimu LONGTEXT.
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
from modules.reports import analiza_service
from modules.reports.analiza_service import DOMYSLNE_WYMIARY, dane_dashboardu
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.reports.uklad import KATALOG, UKLAD_DOMYSLNY, Instancja

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)


@compiles(LONGTEXT, 'sqlite')
def _longtext_jako_text(typ, kompilator, **kw):
    return 'TEXT'


from modules.production.models import ProductionOrder  # noqa: F401 — rejestr mapperów
from modules.users.models import User  # noqa: F401 — rejestr mapperów
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów
from modules.quotes.models import QuoteStatus  # noqa: F401 — rejestr mapperów

OD, DO = date(2026, 9, 1), date(2026, 9, 21)


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    db.init_app(app)
    with app.app_context():
        db.create_all()
        klient = SalesClient(display_name='Firma Testowa', orders_count=1,
                             lifetime_net=Decimal('1000.00'))
        db.session.add(klient)
        db.session.flush()
        zamowienie = SalesOrder(baselinker_order_id=1, client_id=klient.id,
                                date_created=date(2026, 9, 10),
                                order_source='shop', caretaker='Anna',
                                delivery_state='Mazowieckie',
                                delivery_method='Kurier', current_status='Nowe',
                                balance_due=Decimal('100.00'))
        db.session.add(zamowienie)
        db.session.flush()
        db.session.add(SalesOrderItem(
            order_id=zamowienie.id, wood_species='dąb', technology='lity',
            wood_class='A/B', finish_state='surowy', group_type='blat',
            quantity=1, value_net=Decimal('1000.00'),
            total_volume=Decimal('0.100000')))
        db.session.commit()
        yield app
        db.session.remove()


def karta(uklad_instancji):
    return dane_dashboardu(OD, DO, uklad_instancji)


# --- klucze kart są kluczami INSTANCJI --------------------------------------

def test_klucz_karty_to_klucz_instancji(app):
    instancja = Instancja('kanal', 'order_source')
    dane = karta([instancja])
    assert set(dane['karty']) == {'kanal:order_source'}


def test_ten_sam_typ_dwa_razy_daje_dwie_osobne_karty(app):
    """Sedno całej funkcji. Do 23.09.2026 payload miał jeden klucz na TYP,
    więc druga instancja nadpisywałaby pierwszą."""
    dane = karta([Instancja('kanal', 'order_source'),
                  Instancja('kanal', 'caretaker')])
    assert set(dane['karty']) == {'kanal:order_source', 'kanal:caretaker'}


def test_kazda_karta_niesie_swoj_wlasny_wymiar(app):
    dane = karta([Instancja('kanal', 'order_source'),
                  Instancja('kanal', 'caretaker')])
    assert dane['karty']['kanal:order_source']['wymiar'] == 'order_source'
    assert dane['karty']['kanal:caretaker']['wymiar'] == 'caretaker'


def test_uklad_domyslny_daje_dokladnie_dzisiejszy_zestaw_kart(app):
    """STRAŻNIK: układ domyślny musi dawać to, co dashboard dawał przed Planem D."""
    dane = karta(list(UKLAD_DOMYSLNY))
    oczekiwane = {i.klucz for i in UKLAD_DOMYSLNY if KATALOG[i.typ].wymiarowy}
    assert set(dane['karty']) == oczekiwane


def test_pusty_uklad_daje_payload_bez_kart_i_bez_wyjatku(app):
    """Stan pusty musi się wyrenderować, a nie oddać 500."""
    dane = karta([])
    assert dane['karty'] == {}
    assert dane['okres']['od'] == OD


# --- liczymy tylko to, co jest na ekranie -----------------------------------

def test_lejek_jest_none_gdy_nie_ma_go_w_ukladzie(app):
    assert karta([Instancja('kpi')])['lejek'] is None


def test_lejek_jest_wypelniony_gdy_jest_w_ukladzie(app):
    dane = karta([Instancja('lejek')])
    assert dane['lejek'] is not None
    assert 'stopnie' in dane['lejek']


def test_karty_kubelkowe_mieszkaja_w_kartach_pod_kluczem_instancji(app):
    """Do 23.09.2026 „klienci" i „naleznosci" byly kluczami NAJWYZSZEGO poziomu
    payloadu, bo kazda z tych kart wystepowala raz. Odkad moga wystapic trzy
    razy z roznymi wymiarami, musza byc kluczowane instancja jak reszta."""
    from modules.reports.analiza_service import KARTY_KUBELKOWE
    wymiar = KARTY_KUBELKOWE['klienci']['domyslny']
    dane = karta([Instancja('klienci', wymiar)])
    assert 'klienci' not in dane
    assert f'klienci:{wymiar}' in dane['karty']


def test_karta_kubelkowa_niesie_to_samo_co_przed_zmiana(app):
    """Zawartosc bloku jest PRZENIESIONA co do klucza z commita 5206f18,
    nie przepisana."""
    from modules.reports.analiza_service import KARTY_KUBELKOWE
    wymiar = KARTY_KUBELKOWE['klienci']['domyslny']
    blok = karta([Instancja('klienci', wymiar)])['karty'][f'klienci:{wymiar}']
    assert set(blok) >= {'kubelki', 'konwersja', 'nowi_w_okresie', 'wymiar',
                         'wymiary', 'naglowek', 'wiersze', 'ogon', 'uwaga'}


def test_dwie_karty_klientow_z_roznymi_wymiarami_daja_dwa_bloki(app):
    """Doslowny przyklad uzytkownika: „3x klienci wg, ale z roznymi wedlug"."""
    from modules.reports.analiza_service import KARTY_KUBELKOWE
    domyslny = KARTY_KUBELKOWE['klienci']['domyslny']
    dane = karta([Instancja('klienci', domyslny),
                  Instancja('klienci', 'caretaker')])
    assert set(dane['karty']) == {f'klienci:{domyslny}', 'klienci:caretaker'}


def test_karta_naleznosci_z_wymiarem_zamowienia_oddaje_blok_w_ksztalcie_kubelkow(app):
    """Przekroj naleznosci po dozwolonym wymiarze w ogole sie liczy i oddaje
    blok w tym samym ksztalcie, co kubelki.

    NAZWA ZMIENIONA po przegladzie galezi (D5): dawniej obiecywala, ze test
    pilnuje „saldo sie nie zwielokrotnia", a fikstura ma jedna pozycje, wiec
    join z pozycjami dalby ten sam wynik. Prawdziwa ochrona przed
    zwielokrotnieniem salda to test na 34 pozycjach:
    tests/test_analiza_api.py::test_naleznosci_wg_wymiaru_nie_powielaja_salda_przez_pozycje."""
    blok = karta([Instancja('naleznosci', 'caretaker')])['karty']['naleznosci:caretaker']
    assert 'wiersze' in blok and 'ostrzezenie' in blok and 'nadplaty' in blok


def test_kanal_rozbicie_jest_none_gdy_nie_ma_karty_kanalu(app):
    assert karta([Instancja('kpi')])['kanal_rozbicie'] is None


def test_kanal_rozbicie_jest_wypelnione_gdy_jest_karta_kanalu(app):
    dane = karta([Instancja('kanal', 'caretaker')])
    assert dane['kanal_rozbicie'] is not None


def test_koszt_kuriera_jest_none_gdy_nie_ma_karty_dostawy(app):
    assert karta([Instancja('kpi')])['dostawa_koszt_kuriera'] is None


def test_wnioski_sa_none_gdy_nie_ma_karty_statystyk(app):
    assert karta([Instancja('kpi')])['wnioski'] is None


def test_wnioski_sa_wypelnione_gdy_jest_karta_statystyk(app):
    dane = karta([Instancja('wnioski')])
    assert dane['wnioski'] is not None and len(dane['wnioski']) == 3


def test_kpi_i_trend_licza_sie_dla_kafelka_kpi(app):
    dane = karta([Instancja('kpi')])
    assert dane['kpi'] is not None and dane['trend'] is not None


def test_kpi_i_trend_licza_sie_takze_dla_samych_statystyk(app):
    """Karta „Statystyki" czyta `kpi` i `trend`, choc sama ich nie pokazuje.
    Bez tego warunku jej trzy zdania rozsypalyby sie na None."""
    dane = karta([Instancja('wnioski')])
    assert dane['kpi'] is not None and dane['trend'] is not None


def test_kpi_i_trend_sa_none_gdy_nie_czyta_ich_zaden_kafelek(app):
    """26 ms na zapytanie, ktorego nikt nie oglada. Wazniejsze niz oszczednosc:
    `/api/kafelek` (Zadanie 8) prosi o JEDEN kafelek i nie ma powodu liczyc
    przy tym calego paska wskaznikow."""
    dane = karta([Instancja('kanal', 'order_source')])
    assert dane['kpi'] is None and dane['trend'] is None


def test_pusty_uklad_nie_liczy_niczego(app):
    dane = karta([])
    assert dane['karty'] == {} and dane['kpi'] is None and dane['lejek'] is None


# --- dodatki kart wędrują z instancją, nie z typem --------------------------

def test_najlepsze_srednie_liczy_sie_dla_wymiaru_swojej_instancji(app):
    """JEDYNA ochrona dodatku „Najwyższe śr. zamówienie" per instancja.

    Do przeglądu gałęzi (D5) test sprawdzał tylko obecność klucza, więc
    przechodził także wtedy, gdy „najlepszy" liczył się zawsze po opiekunie,
    niezależnie od wymiaru kafelka. Teraz sprawdza ETYKIETĘ: kafelek po
    kanale ma wskazać kanał, kafelek po opiekunie — opiekuna. Fikstura ma
    jedno zamówienie: kanał „shop" (etykieta „Sklep"), opiekun „Anna"."""
    dane = karta([Instancja('opiekun', 'caretaker'),
                  Instancja('opiekun', 'order_source')])
    po_opiekunie = dane['karty']['opiekun:caretaker']['najlepszy']
    po_kanale = dane['karty']['opiekun:order_source']['najlepszy']
    assert po_opiekunie['etykieta'] == 'Anna'
    assert po_kanale['etykieta'] == 'Sklep'
    assert po_opiekunie['srednie'] == po_kanale['srednie'] == Decimal('1000.00')


def test_mapa_pojawia_sie_tylko_przy_wymiarze_wojewodztwa(app):
    dane = karta([Instancja('wojewodztwo', 'delivery_state'),
                  Instancja('wojewodztwo', 'caretaker')])
    assert 'mapa' in dane['karty']['wojewodztwo:delivery_state']
    assert 'mapa' not in dane['karty']['wojewodztwo:caretaker']


def test_roznica_do_surowego_liczy_sie_dla_kazdej_instancji_wykonczenia(app):
    """Do przeglądu gałęzi (D5) test miał jedną instancję i sprawdzał tylko
    obecność klucza — przechodził także wtedy, gdy różnica liczyła się zawsze
    po wykończeniu. Teraz dwie instancje dają RÓŻNE wyniki:

    - po wykończeniu: surowy 1000 zł / 0,1 m³ i olejowany 1500 zł / 0,1 m³,
      czyli m³ z wykończeniem o 50,0% droższy;
    - po gatunku: obie pozycje to dąb, wiersza „surowy" nie ma, więc różnicy
      nie da się policzyć i karta ma pokazać kreskę (None), a nie liczbę
      zapożyczoną z innego kafelka."""
    zamowienie = SalesOrder.query.first()
    db.session.add(SalesOrderItem(
        order_id=zamowienie.id, wood_species='dąb', technology='lity',
        wood_class='A/B', finish_state='olejowany', group_type='blat',
        quantity=1, value_net=Decimal('1500.00'),
        total_volume=Decimal('0.100000')))
    db.session.commit()

    dane = karta([Instancja('wykonczenie', 'finish_state'),
                  Instancja('wykonczenie', 'wood_species')])
    assert dane['karty']['wykonczenie:finish_state']['roznica_do_surowego'] == Decimal('50.0')
    assert dane['karty']['wykonczenie:wood_species']['roznica_do_surowego'] is None


def test_roznica_do_surowego_tylko_na_wymiarze_wykonczenia(app):
    """Porządki końcowe, punkt 2: „Cena za m³ z wykończeniem … wobec surowego"
    ma sens WYŁĄCZNIE, gdy karta pokazuje wykończenia. Na produkcji status
    „W produkcji - surowe" zawiera „surow", więc karta przełączona na Status
    pokazywała np. „-10,7% wobec surowego" — porównanie statusu z resztą
    statusów podpisane jak porównanie wykończeń.

    Dane są tak ułożone, żeby stara reguła („surow" w etykiecie) dała liczbę:
    status „W produkcji - surowe" 1000 zł / 0,1 m³ i „Nowe" 1500 zł / 0,1 m³.
    Na wykończeniu ta sama para daje 50,0%, więc to nie brak danych."""
    zamowienie = SalesOrder.query.first()
    zamowienie.current_status = 'W produkcji - surowe'
    drugie = SalesOrder(baselinker_order_id=2, client_id=zamowienie.client_id,
                        date_created=date(2026, 9, 11), order_source='shop',
                        caretaker='Anna', delivery_state='Mazowieckie',
                        delivery_method='Kurier', current_status='Nowe',
                        balance_due=Decimal('0'))
    db.session.add(drugie)
    db.session.flush()
    db.session.add(SalesOrderItem(
        order_id=drugie.id, wood_species='dąb', technology='lity',
        wood_class='A/B', finish_state='olejowany', group_type='blat',
        quantity=1, value_net=Decimal('1500.00'),
        total_volume=Decimal('0.100000')))
    db.session.commit()

    dane = karta([Instancja('wykonczenie', 'finish_state'),
                  Instancja('wykonczenie', 'current_status')])
    assert dane['karty']['wykonczenie:finish_state']['roznica_do_surowego'] == Decimal('50.0')
    assert dane['karty']['wykonczenie:current_status']['roznica_do_surowego'] is None


# --- wniosek o kanale nie kłamie --------------------------------------------

def test_wniosek_o_kanale_liczy_sie_po_kanale_nawet_bez_karty_kanalu(app):
    """Do 23.09.2026 zdanie „Największy kanał to X" brało wymiar Z KARTY
    kanałów — po przełączeniu jej na „Opiekun" mówiło „Największy kanał to
    Anna Makietowa". Przy własnym układzie karty kanałów może w ogóle nie być.
    Wniosek liczy się teraz ZAWSZE po `order_source`, bo to słowo »kanał«
    w zdaniu obiecuje. To piąty przypadek reguły »ta sama etykieta znaczy
    wszędzie to samo« w tym projekcie."""
    dane = karta([Instancja('wnioski')])
    assert 'Największy kanał to Sklep' in dane['wnioski'][0]['tekst']


def test_wniosek_o_kanale_nie_zmienia_sie_z_wymiarem_karty_kanalow(app):
    bez_karty = karta([Instancja('wnioski')])
    z_inna_karta = karta([Instancja('wnioski'), Instancja('kanal', 'caretaker')])
    assert bez_karty['wnioski'][0]['tekst'] == z_inna_karta['wnioski'][0]['tekst']


# --- pamięć podręczna -------------------------------------------------------

def test_ten_sam_wymiar_na_dwoch_kafelkach_pyta_baze_raz(app, monkeypatch):
    """Zmierzone: 20 kafelków na 4 różnych wymiarach to 306 ms bez pamięci
    i 69 ms z pamięcią. Ten test pilnuje MECHANIZMU, nie czasu."""
    wolania = []
    prawdziwe = analiza_service.wg_wymiaru

    def licz(nazwa, od, do, filtr=None):
        wolania.append((nazwa, od, do, repr(filtr)))
        return prawdziwe(nazwa, od, do, filtr=filtr)

    monkeypatch.setattr(analiza_service, 'wg_wymiaru', licz)
    karta([Instancja('kanal', 'wood_species'), Instancja('mix', 'wood_species')])
    po_gatunku = [w for w in wolania if w[0] == 'wood_species' and w[3] == repr(None)]
    assert len(po_gatunku) == 1, wolania


def test_pamiec_nie_przezywa_zadania(app, monkeypatch):
    """Pamięć modułowa byłaby współdzielona między użytkownikami i między
    okresami — ten sam błąd, co cache cennika per worker (naprawiany 05.08.2026)."""
    wolania = []
    prawdziwe = analiza_service.wg_wymiaru

    def licz(nazwa, od, do, filtr=None):
        wolania.append(nazwa)
        return prawdziwe(nazwa, od, do, filtr=filtr)

    monkeypatch.setattr(analiza_service, 'wg_wymiaru', licz)
    karta([Instancja('kanal', 'wood_species')])
    ile_po_pierwszym = wolania.count('wood_species')
    karta([Instancja('kanal', 'wood_species')])
    assert wolania.count('wood_species') == 2 * ile_po_pierwszym


def test_segment_porownawczy_nie_dziedziczy_wynikow_bazy(app, monkeypatch):
    """Klucz pamięci MUSI zawierać filtr — inaczej karta segmentu dostałaby
    liczby całego okresu i wykres pokazałby dwie identyczne serie."""
    wolania = []
    prawdziwe = analiza_service.wg_wymiaru

    def licz(nazwa, od, do, filtr=None):
        wolania.append((nazwa, repr(filtr)))
        return prawdziwe(nazwa, od, do, filtr=filtr)

    monkeypatch.setattr(analiza_service, 'wg_wymiaru', licz)
    dane_dashboardu(OD, DO, [Instancja('kanal', 'order_source')],
                    porownanie={'order_source': ['shop']})
    filtry = {f for nazwa, f in wolania if nazwa == 'order_source'}
    assert len(filtry) >= 2, 'segment policzył się z tej samej pamięci co baza'


# --- pamięć podręczna kart kubełkowych: praca niezależna od wymiaru --------
# Karty „Klienci według" i „Należności według" mają po trzy funkcje, które
# NIE zależą od wymiaru instancji (tylko ewentualnie od okresu/`na_dzien`) —
# przy kilku kafelkach tego samego typu, ale z różnym „według", mają się
# policzyć raz na żądanie, nie raz na instancję.

def test_funkcje_klientow_niezalezne_od_wymiaru_licza_sie_raz_na_zadanie(app, monkeypatch):
    """Trzy kafelki „Klienci" o RÓŻNYCH wymiarach: `klienci_wg_liczby_zamowien`,
    `konwersja_lead_klient` i `nowi_klienci` nie zależą od wymiaru kafelka
    (tylko ewentualnie okres) — mają się policzyć raz, nie trzy razy."""
    from modules.reports import analytics

    liczniki = {'kubelki': 0, 'konwersja': 0, 'nowi': 0}
    prawdziwe_kubelki = analytics.klienci_wg_liczby_zamowien
    prawdziwa_konwersja = analytics.konwersja_lead_klient
    prawdziwi_nowi = analytics.nowi_klienci

    def kubelki():
        liczniki['kubelki'] += 1
        return prawdziwe_kubelki()

    def konwersja():
        liczniki['konwersja'] += 1
        return prawdziwa_konwersja()

    def nowi(od, do, filtr=None):
        liczniki['nowi'] += 1
        return prawdziwi_nowi(od, do, filtr=filtr)

    monkeypatch.setattr(analytics, 'klienci_wg_liczby_zamowien', kubelki)
    monkeypatch.setattr(analytics, 'konwersja_lead_klient', konwersja)
    monkeypatch.setattr(analytics, 'nowi_klienci', nowi)

    wymiary_klientow = KATALOG['klienci'].wymiary
    assert len(wymiary_klientow) >= 3, 'test zakłada co najmniej 3 wymiary karty klientów'
    karta([Instancja('klienci', w) for w in wymiary_klientow[:3]])

    assert liczniki == {'kubelki': 1, 'konwersja': 1, 'nowi': 1}, liczniki


def test_funkcje_naleznosci_niezalezne_od_wymiaru_licza_sie_raz_na_zadanie(app, monkeypatch):
    """To samo co wyżej, dla trzech kafelków „Należności": `naleznosci_wg_wieku`,
    `ostrzezenie_salda` i `nadplaty` zależą co najwyżej od `na_dzien`, nigdy
    od wymiaru kafelka."""
    from modules.reports import analytics

    liczniki = {'wiek': 0, 'ostrzezenie': 0, 'nadplaty': 0}
    prawdziwy_wiek = analiza_service.naleznosci_wg_wieku
    prawdziwe_ostrzezenie = analytics.ostrzezenie_salda
    prawdziwe_nadplaty = analiza_service.nadplaty

    def wiek(na_dzien, filtr=None):
        liczniki['wiek'] += 1
        return prawdziwy_wiek(na_dzien, filtr=filtr)

    def ostrzezenie(na_dzien, filtr=None):
        liczniki['ostrzezenie'] += 1
        return prawdziwe_ostrzezenie(na_dzien, filtr=filtr)

    def nadplaty_liczone(filtr=None):
        liczniki['nadplaty'] += 1
        return prawdziwe_nadplaty(filtr=filtr)

    monkeypatch.setattr(analiza_service, 'naleznosci_wg_wieku', wiek)
    monkeypatch.setattr(analytics, 'ostrzezenie_salda', ostrzezenie)
    monkeypatch.setattr(analiza_service, 'nadplaty', nadplaty_liczone)

    wymiary_naleznosci = KATALOG['naleznosci'].wymiary
    assert len(wymiary_naleznosci) >= 3, 'test zakłada co najmniej 3 wymiary karty należności'
    karta([Instancja('naleznosci', w) for w in wymiary_naleznosci[:3]])

    assert liczniki == {'wiek': 1, 'ostrzezenie': 1, 'nadplaty': 1}, liczniki


# --- segment porównawczy przy własnym układzie ------------------------------
# Dopisane ponad plan: plan przepisywał `_dane_porownania`, ale nie miał
# testu, że segment idzie za INSTANCJAMI, a nie za typami.

def test_segment_ma_karte_i_ogon_dla_kazdej_instancji(app):
    """Przy dwóch kafelkach tego samego typu przeglądarka musi zestawić drugą
    serię z właściwym kafelkiem — więc klucz segmentu to klucz instancji,
    tak samo w `karty`, jak w `ogony`."""
    dane = dane_dashboardu(OD, DO, [Instancja('kanal', 'order_source'),
                                    Instancja('kanal', 'caretaker')],
                           porownanie={'order_source': ['shop']})
    klucze = {'kanal:order_source', 'kanal:caretaker'}
    assert set(dane['porownanie']['karty']) == klucze
    assert set(dane['porownanie']['ogony']) == klucze


def test_segment_pomija_karty_kubelkowe(app):
    """Kubełki klientów liczą się z całej historii, a należności na dziś —
    druga seria byłaby kłamstwem (spec §6.1.1 i zdanie na samej karcie)."""
    dane = dane_dashboardu(OD, DO, [Instancja('klienci', 'caretaker'),
                                    Instancja('naleznosci', 'caretaker')],
                           porownanie={'order_source': ['shop']})
    assert dane['porownanie']['karty'] == {}


def test_segment_bez_kafelkow_czytajacych_kpi_nie_liczy_kpi(app):
    dane = dane_dashboardu(OD, DO, [Instancja('kanal', 'order_source')],
                           porownanie={'order_source': ['shop']})
    assert dane['porownanie']['kpi'] is None
    assert dane['porownanie']['trend'] is None


def test_segment_bez_karty_kanalu_nie_liczy_rozbicia(app):
    dane = dane_dashboardu(OD, DO, [Instancja('kpi')],
                           porownanie={'order_source': ['shop']})
    assert dane['porownanie']['kanal_rozbicie'] is None
    assert dane['porownanie']['kanal_rozbicie_ogon'] is None
    assert dane['porownanie']['kpi'] is not None


def test_segment_bez_karty_dostawy_nie_liczy_kosztu_kuriera(app):
    """Ta sama reguła co w serii bazowej: liczymy tylko to, co jest na ekranie."""
    bez = dane_dashboardu(OD, DO, [Instancja('kpi')],
                          porownanie={'order_source': ['shop']})
    z_dostawa = dane_dashboardu(OD, DO, [Instancja('dostawa', 'delivery_method')],
                                porownanie={'order_source': ['shop']})
    assert bez['porownanie']['dostawa_koszt_kuriera'] is None
    assert z_dostawa['porownanie']['dostawa_koszt_kuriera'] is not None


# --- pominięte pozycje ------------------------------------------------------

def test_payload_niesie_liczbe_pominietych(app):
    dane = dane_dashboardu(OD, DO, [Instancja('kpi')], )
    assert dane['pominietych'] == 0


def test_payload_przenosi_liczbe_pominietych_od_wolajacego(app):
    dane = dane_dashboardu(OD, DO, [Instancja('kpi')], pominietych=3)
    assert dane['pominietych'] == 3


# --- domyślne wymiary nie zmieniły się --------------------------------------

def test_domyslne_wymiary_sa_wyliczane_z_katalogu(app):
    """ODCHYLENIE od planu: plan brał WSZYSTKIE typy wymiarowe, ale test partii A
    (`test_domyslny_wymiar_typu_zwyklego_zgadza_sie_z_domyslne_wymiary`)
    wymaga wyłącznie typów BEZ własnej listy — `DOMYSLNE_WYMIARY` to pola
    rejestru, a pseudo-wymiar karty kubełkowej polem rejestru nie jest.
    Karty kubełkowe opisuje `KARTY_KUBELKOWE`."""
    z_katalogu = {k: t.domyslny_wymiar for k, t in KATALOG.items()
                  if t.wymiarowy and t.wymiary is None}
    assert dict(DOMYSLNE_WYMIARY) == z_katalogu


def test_domyslne_wymiary_szesciu_pewnych_kart_nie_zmienily_sie(app):
    """Wartości spisane z dashboardu sprzed Planu D. Gdyby wyliczanie
    z katalogu cokolwiek przesunęło, wyjdzie tutaj, a nie na ekranie."""
    assert DOMYSLNE_WYMIARY['kanal'] == 'order_source'
    assert DOMYSLNE_WYMIARY['opiekun'] == 'caretaker'
    assert DOMYSLNE_WYMIARY['mix'] == 'konfiguracja'
    assert DOMYSLNE_WYMIARY['wojewodztwo'] == 'delivery_state'
    assert DOMYSLNE_WYMIARY['wykonczenie'] == 'finish_state'
    assert DOMYSLNE_WYMIARY['dostawa'] == 'delivery_method'


# --- partia E, punkt E1: należności poza układem domyślnym ---------------------

def _zakaz_agregatow_naleznosci(monkeypatch):
    def nie_wolno(*argumenty, **nazwane):
        raise AssertionError('agregat należności policzony, choć karty nie ma na pulpicie')
    monkeypatch.setattr(analiza_service, 'naleznosci_wg_wieku', nie_wolno)
    monkeypatch.setattr(analiza_service, 'naleznosci_wg_wymiaru', nie_wolno)
    monkeypatch.setattr(analiza_service, 'nadplaty', nie_wolno)
    monkeypatch.setattr(analiza_service.analytics, 'ostrzezenie_salda', nie_wolno)


def test_uklad_domyslny_nie_liczy_agregatow_naleznosci(app, monkeypatch):
    """Serwer liczy tylko to, co stoi na pulpicie. Po E1 pierwsze wczytanie
    strony (bez zapisanego układu) nie płaci za kubełki wieku, ostrzeżenie
    o saldzie ani nadpłaty."""
    _zakaz_agregatow_naleznosci(monkeypatch)
    dane = karta(list(UKLAD_DOMYSLNY))
    assert not [k for k in dane['karty'] if k.startswith('naleznosci')]


def test_karta_naleznosci_dodana_do_ukladu_dalej_sie_liczy(app, monkeypatch):
    """Strażnik testu wyżej: te same podmiany WYWRACAJĄ pulpit z kartą
    należności — więc test wyżej naprawdę sprawdza, że jej nie liczymy."""
    _zakaz_agregatow_naleznosci(monkeypatch)
    with pytest.raises(AssertionError):
        karta([Instancja('naleznosci', 'wiek_zamowienia')])
    monkeypatch.undo()
    dane = karta([Instancja('naleznosci', 'wiek_zamowienia')])
    assert dane['karty']['naleznosci:wiek_zamowienia']['kubelki']


# --- partia E, punkt E7 (backend): wymiary wpisane na sztywno w serwisie -------
# Rozbicie kanału ręcznego grupuje po `client_origin` i zawęża filtrem po
# `order_source`, a wniosek „Największy kanał" liczy się po `order_source`.
# Gdy któreś z tych pól straci wymiar=True w `fields.py`, blok ma zwrócić None
# z ostrzeżeniem w logu `reports.uklad`, a pulpit ma się dalej liczyć — tak jak
# katalog kafelków od poprawki M7/B-W1. Rejestr podmieniamy na czas testu,
# pliku `fields.py` nie ruszamy.

import dataclasses  # noqa: E402
import logging  # noqa: E402

from modules.reports import uklad as modul_ukladu  # noqa: E402
from modules.reports.fields import POLA  # noqa: E402


def _bez_wymiaru(monkeypatch, nazwa):
    monkeypatch.setitem(POLA, nazwa, dataclasses.replace(POLA[nazwa], wymiar=False))


def _uklad_domyslny_po_zmianie_rejestru():
    """Układ domyślny taki, jaki zbuduje import po zmianie `fields.py` —
    `_uklad_domyslny` pomija kafelek, którego wymiar przestał być ważny."""
    return list(modul_ukladu._uklad_domyslny([i.typ for i in UKLAD_DOMYSLNY]))


def _ostrzezenia(caplog, fragment):
    return [r for r in caplog.records
            if r.name == 'reports.uklad' and r.levelno >= logging.WARNING
            and fragment in r.getMessage()]


def test_pochodzenie_bez_wymiaru_wylacza_tylko_rozbicie_kanalu(app, monkeypatch, caplog):
    _bez_wymiaru(monkeypatch, 'client_origin')
    with caplog.at_level(logging.WARNING, logger='reports.uklad'):
        dane = karta(_uklad_domyslny_po_zmianie_rejestru())
    assert dane['kanal_rozbicie'] is None
    assert 'kanal:order_source' in dane['karty']
    assert dane['wnioski'] is not None
    assert _ostrzezenia(caplog, 'client_origin')


def test_kanal_bez_wymiaru_wylacza_wniosek_i_rozbicie_a_pulpit_sie_liczy(
        app, monkeypatch, caplog):
    _bez_wymiaru(monkeypatch, 'order_source')
    uklad = _uklad_domyslny_po_zmianie_rejestru() + [Instancja('kanal', 'caretaker')]
    with caplog.at_level(logging.WARNING, logger='reports.uklad'):
        dane = karta(uklad)
    assert dane['wnioski'] is None
    assert dane['kanal_rozbicie'] is None
    assert dane['kpi']['netto'] == Decimal('1000.00')
    assert 'kanal:caretaker' in dane['karty']
    assert _ostrzezenia(caplog, 'order_source')


def test_kanal_bez_wymiaru_nie_wywraca_segmentu_porownawczego(app, monkeypatch):
    _bez_wymiaru(monkeypatch, 'order_source')
    uklad = _uklad_domyslny_po_zmianie_rejestru() + [Instancja('kanal', 'caretaker')]
    dane = dane_dashboardu(OD, DO, uklad, porownanie={'caretaker': ['Anna']})
    assert dane['porownanie']['kanal_rozbicie'] is None
    assert dane['porownanie']['kpi']['netto'] == Decimal('1000.00')
