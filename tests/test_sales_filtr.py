# -*- coding: utf-8 -*-
"""Filtr agregatow: format w adresie i przelozenie na SQL.

Trzy niezmienniki, ktore te testy pilnuja:
1. WSTECZNA ZGODNOSC. filtr=None ma dac dokladnie dzisiejszy wynik. Plan A
   jest zweryfikowany na produkcyjnych danych i to jest jego kontrakt.
2. PULAPKA SALDA. Warunek po polu POZYCJI w zapytaniu po SalesOrder wchodzi
   skorelowanym EXISTS. Dolozony joinem powielilby saldo przez liczbe
   pasujacych pozycji — dokladnie blad 7,58x z poprzednika.
3. Format przechodzi tam i z powrotem. Wartosci z BaseLinkera bywaja brudne
   („680 zl za nasz transport, jesli chce"), wiec przecinek i dwukropek
   w wartosci musza przezyc zapis do adresu i odczyt z niego.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports.aggregates import kpi, naleznosci_wg_wieku, wg_wymiaru
from modules.reports.filters import (
    opis_filtru, parsuj_filtr, warunki_pozycji, warunki_zamowienia, zapisz_filtr,
)
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

# Blok "rejestr mapperow" — patrz docstring tests/test_sales_aggregates.py.
from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

_TABLES = [m.__table__ for m in (SalesClient, SalesOrder, SalesOrderItem)]

OKRES = (date(2026, 9, 1), date(2026, 9, 30))


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


def _zamowienie(bl_id, dzien, saldo='0', kanal='shop', transport=False, pozycje=()):
    """pozycje: lista krotek (netto, objetosc, grupa, gatunek)."""
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien,
                     balance_due=Decimal(saldo), order_source=kanal,
                     own_transport=transport, current_status='Nowe')
    db.session.add(zam)
    db.session.flush()
    for netto, objetosc, grupa, gatunek in pozycje:
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal(netto), total_volume=Decimal(objetosc),
            group_type=grupa, wood_species=gatunek, technology='lity',
            wood_class='A/B', quantity=1))
    return zam


# --- format -----------------------------------------------------------------

def test_parsuje_jeden_warunek():
    assert parsuj_filtr('order_source:shop') == {'order_source': ['shop']}


def test_parsuje_koniunkcje_dwoch_wymiarow():
    assert parsuj_filtr('order_source:shop,wood_species:d%C4%85b') == {
        'order_source': ['shop'], 'wood_species': ['dąb']}


def test_parsuje_alternatywe_wartosci_w_jednym_wymiarze():
    assert parsuj_filtr('wood_species:d%C4%85b|jesion') == {
        'wood_species': ['dąb', 'jesion']}


def test_pusty_tekst_daje_None():
    assert parsuj_filtr(None) is None
    assert parsuj_filtr('') is None
    assert parsuj_filtr('   ') is None


def test_pusta_wartosc_znaczy_brak_wartosci():
    assert parsuj_filtr('client_origin:') == {'client_origin': ['']}


def test_wartosc_ze_znakami_formatu_przechodzi_tam_i_z_powrotem():
    """delivery_method z BaseLinkera bywa wolnym tekstem z przecinkiem."""
    filtr = {'delivery_method': ['Kurier, pobranie: 200 zł|dopłata']}
    assert parsuj_filtr(zapisz_filtr(filtr)) == filtr


def test_zapis_ma_stala_kolejnosc():
    """Ten sam filtr ma dawac ten sam adres — inaczej zakladka przestaje
    wskazywac ten sam widok po zmianie kolejnosci klikniec."""
    a = zapisz_filtr({'wood_species': ['dąb'], 'order_source': ['shop']})
    b = zapisz_filtr({'order_source': ['shop'], 'wood_species': ['dąb']})
    assert a == b
    assert a.startswith('order_source:')


def test_zapis_pustego_filtru_to_pusty_napis():
    assert zapisz_filtr(None) == ''
    assert zapisz_filtr({}) == ''


def test_odrzuca_wymiar_spoza_rejestru():
    with pytest.raises(ValueError):
        parsuj_filtr('paid_cash:100')


def test_odrzuca_wymiar_zlozony():
    """Wartosc wymiaru zlozonego to krotka — nie przechodzi przez ten format."""
    with pytest.raises(ValueError):
        parsuj_filtr('konfiguracja:d%C4%85b')


def test_odrzuca_czlon_bez_dwukropka():
    with pytest.raises(ValueError):
        parsuj_filtr('order_source')


def test_odrzuca_ten_sam_wymiar_dwa_razy():
    """Dwa czlony tego samego wymiaru to alternatywa zapisana zle — mamy na to
    pionowa kreske. Cicha wygrana ostatniego byla by pulapka."""
    with pytest.raises(ValueError):
        parsuj_filtr('order_source:shop,order_source:allegro')


def test_odrzuca_date_ktorej_nie_da_sie_sparsowac():
    """MySQL na porownanie kolumny DATE z napisem odpowiada bledem 1525
    „Incorrect DATE value" i konczy zadanie kodem 500. Zly parametr adresu
    ma polec przy parsowaniu, zeby trasa oddala 400 z powodem po polsku.

    SQLite (na ktorym jada testy) takie porownanie PRZEPUSZCZA, wiec bez tego
    testu blad wychodzi dopiero na produkcji."""
    with pytest.raises(ValueError):
        parsuj_filtr('date_created:nie-data')


def test_odrzuca_date_nieistniejaca_w_kalendarzu():
    """Format sie zgadza, dnia nie ma — dla MySQL-a to ten sam blad 1525."""
    with pytest.raises(ValueError):
        parsuj_filtr('date_created:2026-02-30')


def test_przyjmuje_poprawna_date():
    assert parsuj_filtr('date_created:2026-09-21') == {'date_created': ['2026-09-21']}


def test_pusta_wartosc_dla_daty_przechodzi():
    """Pusta wartosc znaczy „brak wartosci", czyli NULL — dla kazdego typu."""
    assert parsuj_filtr('date_created:') == {'date_created': ['']}


def test_odrzuca_wartosc_logiczna_ktorej_nie_da_sie_jednoznacznie_odwzorowac():
    """own_transport to BOOLEAN. PRZED poprawka kazda wartosc spoza listy slow
    prawdy byla po cichu zamieniana na False (zamiast bledu), wiec
    ?filtr=own_transport:moze zwracalo 423 zamowienia z own_transport = 0
    — liczba, ktora wyglada sensownie i jest niepoprawna. Zmierzone na
    dzialajacej aplikacji przez recenzenta."""
    with pytest.raises(ValueError):
        parsuj_filtr('own_transport:moze')


def test_odrzuca_wartosc_logiczna_pusty_string_nie_jest_tym_samym_co_falsz():
    """'0'/'false'/'nie' to jawny falsz. Cokolwiek innego (spacja, literowka)
    ma polec, a nie zostac cicho odczytane jako Nie."""
    with pytest.raises(ValueError):
        parsuj_filtr('own_transport:nnnie')


def test_przyjmuje_rozpoznane_slowa_falszu_dla_kolumny_logicznej():
    """Falsz musi byc rozpoznawany tak samo jawnie jak prawda — inaczej
    odrzucenie nierozpoznanych wartosci zlapaloby tez legalne 'false'/'nie'/'0',
    ktorych auto-wygenerowane linki filtra (str(False) z SQLAlchemy/MySQL-a)
    faktycznie uzywaja."""
    for slowo in ('0', 'false', 'nie', 'f', 'n', 'False', 'NIE'):
        assert parsuj_filtr(f'own_transport:{slowo}') == {'own_transport': [slowo]}


def test_odrzuca_liczbe_ktorej_nie_da_sie_sparsowac():
    """thickness_cm to DECIMAL na pozycji. Ta sama klasa bledu co przy BOOLEAN:
    MySQL w porownaniu DECIMAL-u z nie-liczba rzutuje ja na 0, wiec bez tej
    poprawki ?filtr=thickness_cm:cokolwiek po cichu dopasowalby wiersze
    z thickness_cm = 0 zamiast oddac 400."""
    with pytest.raises(ValueError):
        parsuj_filtr('thickness_cm:cokolwiek')


def test_przyjmuje_poprawna_liczbe_dziesietna():
    assert parsuj_filtr('thickness_cm:4') == {'thickness_cm': ['4']}
    assert parsuj_filtr('thickness_cm:4.5') == {'thickness_cm': ['4.5']}


def test_warunek_zamowienia_odrzuca_niejednoznaczna_wartosc_logiczna_u_zrodla(app):
    """Poprawka siedzi w `_na_typ_kolumny`, wiec dziala dla KAZDEGO wywolania
    — nie tylko przy parsowaniu adresu (`parsuj_filtr`), ale i wtedy, gdy
    ktos zbuduje warunek SQL wprost ze slownika, tak jak robia to
    `warunki_pozycji`/`warunki_zamowienia`."""
    with app.app_context():
        with pytest.raises(ValueError):
            warunki_zamowienia({'own_transport': ['moze']})


def test_pusta_wartosc_kolumny_nietekstowej_pyta_TYLKO_o_null(app):
    """`kolumna = ''` przy BOOLEAN to cicha bledna liczba: MySQL rzutuje
    pusty napis na 0, wiec ?filtr=own_transport: oddawalo 3324 zamowienia
    i pelne 4,4 mln zl netto zamiast zera. Przy DATE to wprost blad 1525.

    SQLite nie odtwarza ani jednego, ani drugiego — dlatego sprawdzamy KSZTALT
    warunku, a nie wynik zapytania."""
    with app.app_context():
        for wymiar in ('own_transport', 'date_created', 'picked_up'):
            warunek = str(warunki_zamowienia({wymiar: ['']})[0])
            assert 'IS NULL' in warunek, wymiar
            assert '=' not in warunek, f'{wymiar}: warunek porownuje z pusta wartoscia'


def test_pusta_wartosc_kolumny_tekstowej_lapie_tez_pusty_napis(app):
    """Dla tekstu oba warianty maja sens — BaseLinker zapisuje i NULL, i ''."""
    with app.app_context():
        warunek = str(warunki_zamowienia({'order_source': ['']})[0])
        assert 'IS NULL' in warunek
        assert '=' in warunek

        # thickness_cm to DECIMAL na POZYCJI — warunek wchodzi EXISTS-em,
        # ale wariant `= ''` ma w nim nie byc z tego samego powodu.
        exists = str(warunki_zamowienia({'thickness_cm': ['']})[0])
        assert 'IS NULL' in exists
        assert 'thickness_cm =' not in exists


def test_opis_filtru_po_polsku():
    assert opis_filtru({'wood_species': ['dąb']}) == 'Gatunek: dąb'
    assert opis_filtru({'order_source': ['shop', 'allegro']}) == 'Kanał sprzedaży: shop, allegro'
    assert opis_filtru(None) == 'brak'


def test_opis_filtru_skraca_dluga_liste():
    opis = opis_filtru({'wood_species': ['dąb', 'jesion', 'buk', 'sosna']})
    assert opis == 'Gatunek: dąb, jesion +2'


# --- regresja: filtr=None ---------------------------------------------------

def test_filtr_None_nie_zmienia_kpi(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), saldo='500.00',
                    pozycje=[('1000.00', '0.50', 'towar', 'dąb')])
        db.session.commit()

        assert kpi(*OKRES) == kpi(*OKRES, filtr=None)
        assert kpi(*OKRES)['saldo'] == Decimal('500.00')


def test_filtr_None_nie_zmienia_wg_wymiaru(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), pozycje=[('1000.00', '0.50', 'towar', 'dąb')])
        db.session.commit()

        assert wg_wymiaru('order_source', *OKRES) == \
            wg_wymiaru('order_source', *OKRES, filtr=None)


def test_filtr_None_nie_zmienia_naleznosci(app):
    with app.app_context():
        _zamowienie(1, date(2026, 5, 2), saldo='300.00',
                    pozycje=[('1000.00', '0.50', 'towar', 'dąb')])
        db.session.commit()

        assert naleznosci_wg_wieku(date(2026, 9, 21)) == \
            naleznosci_wg_wieku(date(2026, 9, 21), filtr=None)


# --- filtr po polu zamówienia -----------------------------------------------

def test_filtr_po_polu_zamowienia_zaweza_kpi(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), saldo='500.00', kanal='shop',
                    pozycje=[('1000.00', '0.50', 'towar', 'dąb')])
        _zamowienie(2, date(2026, 9, 3), saldo='300.00', kanal='allegro',
                    pozycje=[('400.00', '0.20', 'towar', 'dąb')])
        db.session.commit()

        wynik = kpi(*OKRES, filtr={'order_source': ['shop']})

        assert wynik['netto'] == Decimal('1000.00')
        assert wynik['saldo'] == Decimal('500.00')
        assert wynik['zamowienia'] == 1


def test_filtr_lapie_pusta_wartosc_czyli_null(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), kanal=None,
                    pozycje=[('100.00', '0.10', 'towar', 'dąb')])
        _zamowienie(2, date(2026, 9, 3), kanal='shop',
                    pozycje=[('900.00', '0.90', 'towar', 'dąb')])
        db.session.commit()

        assert kpi(*OKRES, filtr={'order_source': ['']})['netto'] == Decimal('100.00')


def test_filtr_po_kolumnie_logicznej_rozumie_tekst_z_adresu(app):
    """own_transport to BOOLEAN. Porownanie kolumny z napisem 'True' nigdy nic
    nie znajdzie na MySQL-u (TINYINT) i bywa, ze znajdzie za duzo na SQLite."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), transport=True,
                    pozycje=[('100.00', '0.10', 'towar', 'dąb')])
        _zamowienie(2, date(2026, 9, 3), transport=False,
                    pozycje=[('900.00', '0.90', 'towar', 'dąb')])
        db.session.commit()

        assert kpi(*OKRES, filtr={'own_transport': ['true']})['netto'] == Decimal('100.00')
        assert kpi(*OKRES, filtr={'own_transport': ['false']})['netto'] == Decimal('900.00')


# --- filtr po polu pozycji: PUŁAPKA SALDA -----------------------------------

def test_filtr_po_polu_pozycji_nie_powiela_salda(app):
    """REGRESJA na blad 7,58x. Zamowienie ma 34 debowe pozycje i saldo 9969,32.
    Filtr „gatunek = dab" ma dac 9969,32, a nie 34 x tyle."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), saldo='9969.32',
                    pozycje=[('100.00', '0.01', 'towar', 'dąb')] * 34)
        db.session.commit()

        wynik = kpi(*OKRES, filtr={'wood_species': ['dąb']})

        assert wynik['saldo'] == Decimal('9969.32')
        assert wynik['zamowienia'] == 1


def test_filtr_po_polu_pozycji_liczy_netto_tylko_z_pasujacych_pozycji(app):
    """Netto i objetosc zyja na pozycji, wiec filtr po pozycji je zaweza.
    Saldo zyje na zamowieniu, wiec zaweza sie przez EXISTS — do calego salda
    zamowienia, ktore pasujaca pozycje zawiera."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), saldo='500.00', pozycje=[
            ('600.00', '0.30', 'towar', 'dąb'),
            ('400.00', '0.20', 'towar', 'jesion'),
        ])
        db.session.commit()

        wynik = kpi(*OKRES, filtr={'wood_species': ['dąb']})

        assert wynik['netto'] == Decimal('600.00')
        assert wynik['objetosc'] == Decimal('0.30')
        assert wynik['saldo'] == Decimal('500.00')
        assert wynik['zamowienia'] == 1


def test_filtr_po_polu_pozycji_odrzuca_zamowienie_bez_pasujacej_pozycji(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), saldo='500.00',
                    pozycje=[('600.00', '0.30', 'towar', 'dąb')])
        _zamowienie(2, date(2026, 9, 3), saldo='700.00',
                    pozycje=[('400.00', '0.20', 'towar', 'jesion')])
        db.session.commit()

        wynik = kpi(*OKRES, filtr={'wood_species': ['dąb']})

        assert wynik['saldo'] == Decimal('500.00')
        assert wynik['zamowienia'] == 1


def test_filtr_alternatywa_laczy_wartosci_jednego_wymiaru(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), kanal='shop',
                    pozycje=[('100.00', '0.10', 'towar', 'dąb')])
        _zamowienie(2, date(2026, 9, 3), kanal='allegro',
                    pozycje=[('200.00', '0.20', 'towar', 'dąb')])
        _zamowienie(3, date(2026, 9, 4), kanal='olx',
                    pozycje=[('400.00', '0.40', 'towar', 'dąb')])
        db.session.commit()

        wynik = kpi(*OKRES, filtr={'order_source': ['shop', 'allegro']})

        assert wynik['netto'] == Decimal('300.00')
        assert wynik['zamowienia'] == 2


def test_filtr_po_kanale_partycjonuje_zamowienia_bez_straty(app):
    """Niezmiennik z Kroku 6 briefu Zadania 2: liczba zamowien z filtrem po
    kazdej wartosci kanalu, zsumowana po wszystkich kanalach, ma sie zgadzac
    z liczba zamowien bez filtra — zaden rekord nie ginie ani nie dubluje sie
    miedzy wartosciami jednego wymiaru. Na produkcyjnym MySQL-u to samo
    sprawdzenie wykonane recznie (docker compose exec -T app, okres
    2026-01-01..2026-09-21): 993 + 483 + 869 + 10 + 0 = 2355 = kpi() bez
    filtra. Tutaj utrwalone jako test regresyjny, zeby nie polegac wylacznie
    na jednorazowym, recznym uruchomieniu."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), kanal='shop',
                    pozycje=[('100.00', '0.10', 'towar', 'dąb')])
        _zamowienie(2, date(2026, 9, 3), kanal='allegro',
                    pozycje=[('200.00', '0.20', 'towar', 'dąb')])
        _zamowienie(3, date(2026, 9, 4), kanal='olx',
                    pozycje=[('400.00', '0.40', 'towar', 'dąb')])
        _zamowienie(4, date(2026, 9, 5), kanal='shop',
                    pozycje=[('150.00', '0.15', 'towar', 'jesion')])
        db.session.commit()

        bez_filtra = kpi(*OKRES)['zamowienia']
        suma_po_kanalach = sum(
            kpi(*OKRES, filtr={'order_source': [kanal]})['zamowienia']
            for kanal in ('shop', 'allegro', 'olx')
        )

        assert bez_filtra == 4
        assert suma_po_kanalach == bez_filtra


def test_filtr_koniunkcja_zaweza_po_dwoch_wymiarach(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), kanal='shop',
                    pozycje=[('100.00', '0.10', 'towar', 'dąb')])
        _zamowienie(2, date(2026, 9, 3), kanal='shop',
                    pozycje=[('200.00', '0.20', 'towar', 'jesion')])
        _zamowienie(3, date(2026, 9, 4), kanal='allegro',
                    pozycje=[('400.00', '0.40', 'towar', 'dąb')])
        db.session.commit()

        wynik = kpi(*OKRES, filtr={'order_source': ['shop'], 'wood_species': ['dąb']})

        assert wynik['netto'] == Decimal('100.00')
        assert wynik['zamowienia'] == 1


def test_filtr_zaweza_wg_wymiaru(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), kanal='shop', pozycje=[
            ('600.00', '0.30', 'towar', 'dąb'),
            ('400.00', '0.20', 'towar', 'jesion'),
        ])
        db.session.commit()

        wiersze = wg_wymiaru('order_source', *OKRES, filtr={'wood_species': ['dąb']})

        # `sztuki` (24.09.2026) — sztuki produktow z tego samego zapytania.
        assert wiersze == [{'wartosc': 'shop', 'netto': Decimal('600.00'),
                            'objetosc': Decimal('0.30'), 'sztuki': 1,
                            'zamowienia': 1}]


def test_filtr_zaweza_naleznosci_wg_wieku(app):
    """naleznosci_wg_wieku nie ma okresu — liczy z calej historii, wiec filtr
    jest jedynym sposobem zawezenia i tym bardziej nie moze powielac salda."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 10), saldo='500.00', kanal='shop',
                    pozycje=[('100.00', '0.01', 'towar', 'dąb')] * 12)
        _zamowienie(2, date(2026, 9, 11), saldo='700.00', kanal='allegro',
                    pozycje=[('100.00', '0.10', 'towar', 'dąb')])
        db.session.commit()

        kubelki = {k['kubelek']: k
                   for k in naleznosci_wg_wieku(date(2026, 9, 21),
                                                filtr={'order_source': ['shop']})}

        assert kubelki['0-14 dni']['saldo'] == Decimal('500.00')
        assert kubelki['0-14 dni']['zamowienia'] == 1


# --- kształt warunków -------------------------------------------------------

def test_pusty_filtr_nie_dodaje_warunkow_filtra(app):
    """Pusty filtr nie zawęża NICZEGO ponad warunek stały „tylko sprzedaż"
    (partia E, punkt E5) — a bez niego (Arkusz) daje pustą listę."""
    with app.app_context():
        for pusty in (None, {}):
            assert warunki_pozycji(pusty, tylko_sprzedaz=False) == []
            assert warunki_zamowienia(pusty, tylko_sprzedaz=False) == []
            for warunki in (warunki_pozycji(pusty), warunki_zamowienia(pusty)):
                assert len(warunki) == 1
                assert 'baselinker_status_id' in str(warunki[0])


def test_warunek_zamowienia_dla_pola_pozycji_jest_exists(app):
    """Test na KSZTALT zapytania, nie na wynik: EXISTS jest tu jedyna forma,
    ktora nie zwielokrotnia wierszy zamowienia."""
    with app.app_context():
        sql = str(warunki_zamowienia({'wood_species': ['dąb']})[0])
        assert 'EXISTS' in sql.upper()
        assert 'sales_order_items' in sql


def test_warunek_zamowienia_dla_pola_zamowienia_nie_jest_exists(app):
    with app.app_context():
        sql = str(warunki_zamowienia({'order_source': ['shop']})[0])
        assert 'EXISTS' not in sql.upper()


def test_zamowienie_z_data_z_przyszlosci_nie_znika_z_kubelkow(app):
    """Wiek < 0 nie trafial do zadnego kubelka, wiec suma kubelkow przestawala
    sie zgadzac z saldem calosci. Dzis takich wierszy jest 0, ale jedna
    literowka w dacie w BaseLinkerze to zmienia."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 25), saldo='500.00',
                    pozycje=[('100.00', '0.10', 'towar', 'dąb')])
        db.session.commit()

        kubelki = naleznosci_wg_wieku(date(2026, 9, 20))

        assert sum(k['saldo'] for k in kubelki) == Decimal('500.00')
        assert sum(k['zamowienia'] for k in kubelki) == 1
        pierwszy = [k for k in kubelki if k['kubelek'] == '0-14 dni'][0]
        assert pierwszy['saldo'] == Decimal('500.00')
