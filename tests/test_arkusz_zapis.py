# -*- coding: utf-8 -*-
"""Serwis zapisu arkusza: walidacja wejscia i kolumny CRM w transakcji.

Endpoint zapisu przyjmuje wartosci pisane recznie do dowolnej z 55 kolumn —
to najszersze wejscie w calym projekcie. Przeglad Planu B znalazl trzy bledy
krytyczne dajace 500 i WSZYSTKIE TRZY byly w walidacji wejscia, wiec
przypadki brzegowe sa tu projektowane razem z implementacja, nie zostawiane
przegladowi.
"""
import os
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
from modules.reports.arkusz_zapis import BladWalidacji, Zmiana, parsuj_zmiany, zapisz
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.users.models import User

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

_TABLES = [m.__table__ for m in (User, SalesClient, SalesOrder, SalesOrderItem)]


class Rola:
    """Najmniejszy obiekt, jaki wystarcza serwisowi: ma is_admin()."""
    def __init__(self, admin):
        self._admin = admin

    def is_admin(self):
        return self._admin


ADMIN = Rola(True)
HANDLOWIEC = Rola(False)


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    app.config['SECRET_KEY'] = 'test'
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def dane(app):
    """Jedno zamowienie z dwiema pozycjami. Zwraca (id_zamowienia, [id_pozycji]).

    price_type='brutto' jest tu WPROST, bo od domkniecia Planu C zapis wplaty
    do BaseLinkera wymaga oznaczonego typu ceny (patrz `_platnosc_brutto`).
    W bazie tak wyglada 2913 zamowien z 3324; trzy bez oznaczenia maja wlasne
    testy nizej ("--- brak typu ceny ---").
    """
    with app.app_context():
        zam = SalesOrder(baselinker_order_id=50854536, date_created=date(2026, 9, 18),
                         customer_name='Jan Przykładowy', delivery_state='śląskie',
                         client_origin='Sklep', paid_cash=Decimal('0.00'),
                         price_type='brutto',
                         paid_amount=Decimal('0.00'), balance_due=Decimal('0.00'),
                         own_transport=False, picked_up=False)
        db.session.add(zam)
        db.session.flush()
        pozycje = []
        for i, bl in enumerate((991, None)):
            poz = SalesOrderItem(order_id=zam.id, bl_order_product_id=bl,
                                 wood_species='dąb', technology='lity', quantity=1,
                                 price_gross=Decimal('984.00'), value_net=Decimal('800.00'))
            db.session.add(poz)
            db.session.flush()
            pozycje.append(poz.id)
        db.session.commit()
        return zam.id, pozycje


# ===== walidacja wejscia ===============================================

@pytest.mark.parametrize('cialo', [
    None, {}, {'zmiany': None}, {'zmiany': 'tekst'}, {'zmiany': []},
])
def test_zapis_wymaga_niepustej_listy_zmian(cialo):
    with pytest.raises(BladWalidacji):
        parsuj_zmiany(cialo)


@pytest.mark.parametrize('zmiana', [
    {'id': 1, 'nazwa': 'client_origin', 'jest': 'x', 'bylo': ''},        # brak poziomu
    {'poziom': 'klient', 'id': 1, 'nazwa': 'client_origin', 'jest': 'x', 'bylo': ''},
    {'poziom': 'zamowienie', 'id': 'abc', 'nazwa': 'client_origin', 'jest': 'x', 'bylo': ''},
    {'poziom': 'zamowienie', 'id': 0, 'nazwa': 'client_origin', 'jest': 'x', 'bylo': ''},
    {'poziom': 'zamowienie', 'id': 1, 'nazwa': 'nie_ma_takiej', 'jest': 'x', 'bylo': ''},
    {'poziom': 'zamowienie', 'id': 1, 'nazwa': 'konfiguracja', 'jest': 'x', 'bylo': ''},
    {'poziom': 'zamowienie', 'id': 1, 'nazwa': 'client_origin', 'bylo': 'x'},  # brak 'jest'
    {'poziom': 'zamowienie', 'id': 1, 'nazwa': 'client_origin', 'jest': 'x'},  # brak 'bylo'
    'nie slownik',
])
def test_zapis_odrzuca_zle_zbudowana_zmiane(zmiana):
    with pytest.raises(BladWalidacji):
        parsuj_zmiany({'zmiany': [zmiana]})


def test_zapis_odrzuca_paczke_ponad_limit():
    from modules.reports.arkusz_zapis import MAKS_ZMIAN
    wzor = {'poziom': 'zamowienie', 'id': 1, 'nazwa': 'client_origin',
            'jest': 'x', 'bylo': ''}
    with pytest.raises(BladWalidacji):
        parsuj_zmiany({'zmiany': [dict(wzor) for _ in range(MAKS_ZMIAN + 1)]})


def test_zapis_odrzuca_identyfikator_wiekszy_niz_int():
    # Kolumny `id` sa INT, nie BIGINT. Bez gornej granicy 10**30 dociera do
    # Model.query.get(), gdzie na SQLite rzuca OverflowError PRZED
    # try/except w zapisz() - endpoint oddawal 500 zamiast czytelnego 400
    # (przeglad Zadania 10, [WAZNE]).
    with pytest.raises(BladWalidacji):
        parsuj_zmiany({'zmiany': [{'poziom': 'zamowienie', 'id': 10 ** 30,
                                   'nazwa': 'client_origin', 'jest': 'x', 'bylo': ''}]})


def test_endpoint_zapisu_odrzuca_zbyt_duzy_identyfikator_kodem_400(klient_http):
    # Powtorka powyzszego przypadku przez test_client POST, tak jak zostal
    # zmierzony w przegladzie - zamiast 500 oczekujemy czytelnego 400.
    odpowiedz = klient_http.post('/reports/api/arkusz/zapisz', json={'zmiany': [
        {'poziom': 'zamowienie', 'id': 10 ** 30, 'nazwa': 'client_origin',
         'jest': 'x', 'bylo': ''}]})
    assert odpowiedz.status_code == 400


def test_zapis_odrzuca_paczke_z_powtorzonym_kluczem_zmiany():
    # Zadanie 12 odnajduje komorke po kluczu (poziom:id:nazwa) - dwie zmiany
    # o tym samym kluczu w jednej paczce dawaly DWA wyniki 'zapisane', a
    # w bazie zostawala tylko wartosc z DRUGIEJ zmiany (przeglad Zadania 10,
    # [WAZNE]).
    with pytest.raises(BladWalidacji):
        parsuj_zmiany({'zmiany': [
            {'poziom': 'zamowienie', 'id': 1, 'nazwa': 'paid_cash',
             'jest': '100.00', 'bylo': '0.00'},
            {'poziom': 'zamowienie', 'id': 1, 'nazwa': 'paid_cash',
             'jest': '200.00', 'bylo': '0.00'},
        ]})


@pytest.mark.parametrize('nazwa', ['date_created', 'value_net', 'gluing_done_at',
                                   'order_source'])
def test_zapis_odrzuca_kolumne_nieedytowalna(app, dane, nazwa):
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, nazwa, 'cokolwiek')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert 'nie jest edytowalna' in wynik['wyniki'][0]['blad']


def test_zapis_odrzuca_niezgodny_poziom(app, dane):
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('pozycja', id_zam, 'client_origin', 'Detal')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert 'poziom' in wynik['wyniki'][0]['blad']


def test_zapis_odrzuca_wartosc_dluzsza_niz_limit(app, dane):
    # Limit 200 znakow na admin_comments jest po stronie CRM, PRZED wysylka
    # do BaseLinkera (spec 9).
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'notes', 'x' * 201)], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert '200' in wynik['wyniki'][0]['blad']


def test_zapis_odrzuca_kolumne_crm_dluzsza_niz_kolumna_w_bazie(app, dane):
    # client_origin jest VARCHAR(50) w modelu, ale Pole.max_dlugosc (limit API
    # BaseLinkera) go NIE MA - to pole tam nie idzie. Bez limitu z modelu
    # kolumny CRM-owe nie mialy zadnej gornej granicy, a kontener bazy chodzi
    # w STRICT_TRANS_TABLES: kazdy nadmiar to ERROR 1406 na commit, ktory
    # kasowal CALA paczke kolumn CRM (przeglad Zadania 10, [KRYTYCZNE]).
    # Druga zmiana (inne, tez czysto CRM-owe pole) ma przejsc bez przeszkod —
    # walidacja jest per pole, nie per paczka.
    id_zam, pozycje = dane
    with app.app_context():
        wynik = zapisz([
            Zmiana('zamowienie', id_zam, 'client_origin', 'Poprawna wartosc'),
            Zmiana('pozycja', pozycje[0], 'wood_species', 'x' * 51),
        ], ADMIN)
        assert wynik['zapisane'] == 1 and wynik['odrzucone'] == 1
        assert '50' in [w for w in wynik['wyniki'] if w['status'] == 'odrzucone'][0]['blad']
        assert SalesOrder.query.get(id_zam).client_origin == 'Poprawna wartosc'


def test_zapis_odrzuca_pozycje_dluzsza_niz_kolumna_w_bazie(app, dane):
    # wood_class to VARCHAR(10) w sales_order_items, kolumna czysto CRM-owa.
    _, pozycje = dane
    with app.app_context():
        wynik = zapisz([Zmiana('pozycja', pozycje[0], 'wood_class', 'x' * 11)], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert '10' in wynik['wyniki'][0]['blad']
        assert SalesOrderItem.query.get(pozycje[0]).wood_class is None


def test_konwersja_odrzuca_tekst_dluzszy_niz_kolumna_w_bazie():
    # Ta sama walidacja jako CZYSTA funkcja - `na_wartosc` jest wolana wprost
    # przez sam siebie, nie tylko przez `_sprawdz`.
    from modules.reports.arkusz_service import kolumna_arkusza
    from modules.reports.arkusz_zapis import na_wartosc
    with pytest.raises(ValueError) as blad:
        na_wartosc(kolumna_arkusza('client_origin'), 'x' * 51)
    assert '50' in str(blad.value)


@pytest.mark.parametrize('nazwa, wartosc, fragment', [
    ('paid_cash', 'abc', 'liczbą'),
    ('paid_cash', '10,50', 'liczbą'),
    ('quantity', '1.5', 'całkowitą'),
    ('payment_date', '31-12-2026', 'RRRR-MM-DD'),
    ('current_status', 'Wymyślony status', 'nie jest znanym statusem'),
    ('own_transport', 'moze', 'tak'),
])
def test_konwersja_odrzuca_wartosc_zlego_typu(nazwa, wartosc, fragment):
    # Czysta funkcja — testujemy ja osobno, bo dla kolumn z BaseLinkera
    # zapisz() odrzuca zmiane WCZESNIEJ (brak klienta API) i nigdy nie
    # dochodzi do konwersji.
    from modules.reports.arkusz_service import kolumna_arkusza
    from modules.reports.arkusz_zapis import na_wartosc
    with pytest.raises(ValueError) as blad:
        na_wartosc(kolumna_arkusza(nazwa), wartosc)
    assert fragment in str(blad.value)


@pytest.mark.parametrize('wartosc', [
    'NaN', 'nan', 'Infinity', '-Infinity', 'inf', 'sNaN',
])
def test_konwersja_odrzuca_wartosc_specjalna_kwoty(wartosc):
    # Decimal(tekst) NIE rzuca InvalidOperation dla tych napisow - wszystkie
    # "poprawnie" parsuja sie na NaN/nieskonczonosc (przeglad Zadania 10,
    # [KRYTYCZNE]).
    from modules.reports.arkusz_service import kolumna_arkusza
    from modules.reports.arkusz_zapis import na_wartosc
    with pytest.raises(ValueError) as blad:
        na_wartosc(kolumna_arkusza('paid_cash'), wartosc)
    assert 'liczbą' in str(blad.value)


def test_konwersja_odrzuca_kwote_za_duza_dla_kolumny():
    # '1E+40' jest poprawnym, SKONCZONYM Decimalem, wiec go nie lapie
    # sprawdzenie is_finite() - musi go zlapac osobny zakres kolumny.
    from modules.reports.arkusz_service import kolumna_arkusza
    from modules.reports.arkusz_zapis import na_wartosc
    with pytest.raises(ValueError) as blad:
        na_wartosc(kolumna_arkusza('paid_cash'), '1E+40')
    assert 'za duża' in str(blad.value)


def test_zapis_odrzuca_nieskonczonosc_w_kolumnie_kwotowej(app, dane):
    # Na SQLite (caly pakiet testow) Decimal('Infinity') zapisywalo sie po
    # cichu i trulo kazda sume w stopce i na dashboardzie.
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_cash', 'Infinity')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert SalesOrder.query.get(id_zam).paid_cash == Decimal('0.00')


def test_zapis_odrzuca_kwote_poza_zakresem_kolumny_w_bazie(app, dane):
    # decimal(10,2): 14-cyfrowa liczba to normalne dzialanie uzytkownika
    # (literowka, wklejony numer konta) w polu "Zaplacono gotowka"
    # (<input type=number> nie ogranicza zakresu). Na MySQL-u to ERROR 1264,
    # ktory bez tej walidacji kasowal cala paczke kolumn CRM.
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_cash',
                               '99999999999999')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert 'za duża' in wynik['wyniki'][0]['blad']
        assert SalesOrder.query.get(id_zam).paid_cash == Decimal('0.00')


def test_zapis_odrzuca_wartosc_zlego_typu_w_kolumnie_crm(app, dane):
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_cash', 'abc')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert 'liczbą' in wynik['wyniki'][0]['blad']


def test_zapis_odrzuca_nieistniejacy_wiersz(app, dane):
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', 999999, 'client_origin', 'Detal')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert 'nie istnieje' in wynik['wyniki'][0]['blad']


def test_odrzucona_zmiana_nie_blokuje_poprawnej(app, dane):
    # Walidacja per pole, nie per paczka: jedna zla wartosc nie ma prawa
    # skasowac pracy uzytkownika w pozostalych komorkach.
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([
            Zmiana('zamowienie', id_zam, 'client_origin', 'Nowy B2B'),
            Zmiana('zamowienie', id_zam, 'paid_cash', 'abc'),
        ], ADMIN)
        assert wynik['zapisane'] == 1 and wynik['odrzucone'] == 1
        assert SalesOrder.query.get(id_zam).client_origin == 'Nowy B2B'


def test_zapis_odrzuca_pusta_wartosc_w_kolumnie_not_null(app, dane):
    # paid_cash jest decimal(10,2) NOT NULL. `na_wartosc` zwraca dla pustego
    # tekstu bezwarunkowo None, a `setattr(..., None)` na commicie wywala
    # IntegrityError - i bez sprawdzenia PRZED sesja kasowal CALA paczke,
    # w tym poprawna zmiane client_origin obok (przeglad Zadania 10,
    # [KRYTYCZNE]).
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([
            Zmiana('zamowienie', id_zam, 'client_origin', 'Nowy B2B'),
            Zmiana('zamowienie', id_zam, 'paid_cash', ''),
        ], ADMIN)
        assert wynik['zapisane'] == 1 and wynik['odrzucone'] == 1
        zam = SalesOrder.query.get(id_zam)
        assert zam.client_origin == 'Nowy B2B'
        assert zam.paid_cash == Decimal('0.00')
        odrzucone = [w for w in wynik['wyniki'] if w['status'] == 'odrzucone'][0]
        assert 'puste' in odrzucone['blad']


def test_zapis_odrzuca_pusta_wartosc_w_kolumnie_logicznej_not_null(app, dane):
    # own_transport jest Boolean NOT NULL - inny typ danych, ta sama pulapka.
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'own_transport', '')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert 'puste' in wynik['wyniki'][0]['blad']
        assert SalesOrder.query.get(id_zam).own_transport is False


# ===== straznik optymistyczny ==========================================

def test_zmiana_odrzucona_gdy_ktos_zmienil_wartosc_w_miedzyczasie(app, dane):
    # Dwie osoby w tym samym arkuszu. Bez straznika wygrywalby ten, kto
    # kliknie „Zapisz" jako drugi — po cichu, bez ani jednego komunikatu.
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'client_origin', 'Detal',
                               bylo='Nowy B2B')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert 'w międzyczasie' in wynik['wyniki'][0]['blad']
        assert SalesOrder.query.get(id_zam).client_origin == 'Sklep'


def test_straznik_przepuszcza_gdy_wartosc_pierwotna_sie_zgadza(app, dane):
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'client_origin', 'Detal',
                               bylo='Sklep')], ADMIN)
        assert wynik['zapisane'] == 1
        assert SalesOrder.query.get(id_zam).client_origin == 'Detal'


def test_straznik_porownuje_wartosc_surowa_a_nie_sformatowana(app, dane):
    # „1 338,36" to tekst na ekranie, „1338.36" to wartosc. Porownanie po
    # tekscie odrzucaloby KAZDA zmiane kwoty.
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_cash', '1338.36',
                               bylo='0.00')], ADMIN)
        assert wynik['zapisane'] == 1, wynik['wyniki'][0].get('blad')


def test_straznik_odrzuca_tylko_swoja_komorke(app, dane):
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([
            Zmiana('zamowienie', id_zam, 'client_origin', 'Detal', bylo='Nowy B2B'),
            Zmiana('zamowienie', id_zam, 'paid_cash', '50.00', bylo='0.00'),
        ], ADMIN)
        assert wynik['zapisane'] == 1 and wynik['odrzucone'] == 1
        zam = SalesOrder.query.get(id_zam)
        assert zam.client_origin == 'Sklep'
        assert zam.paid_cash == Decimal('50.00')


def test_straznik_nie_odrzuca_gdy_kwota_zapisana_wczesniej_inaczej_zaokraglona(app, dane):
    # Zapis '2.7' laduje w bazie jako Decimal('2.70') (skala kolumny = 2).
    # Serwer zwraca WYLACZNIE tekst sformatowany ('2,70'), nigdy kanonicznej
    # wartosci surowej - wiec przegladarka wciaz pamieta '2.7' jako wartosc
    # pierwotna. DRUGA edycja tej samej komorki nie moze dostac falszywego
    # "ktos to zmienil w miedzyczasie" (przeglad Zadania 10, [WAZNE]).
    _, pozycje = dane
    with app.app_context():
        zapisz([Zmiana('pozycja', pozycje[0], 'thickness_cm', '2.7')], ADMIN)
        wynik = zapisz([Zmiana('pozycja', pozycje[0], 'thickness_cm', '3.5',
                               bylo='2.7')], ADMIN)
        assert wynik['zapisane'] == 1, wynik['wyniki'][0].get('blad')
        assert SalesOrderItem.query.get(pozycje[0]).thickness_cm == Decimal('3.50')


def test_straznik_traktuje_pusty_napis_i_brak_wartosci_tak_samo(app, dane):
    # Kolumny synchronizowane z BaseLinkera (np. e-mail) czasem trzymaja
    # pusty napis, nie NULL (ingest.py:_tekst_zamowienia) - strażnik nie moze
    # na tym falszywie wykrywac "zmiane rownolegla".
    # ODCHYLENIE (Zadanie 11): oryginalny test z Zadania 10 oczekiwal komunikatu
    # stanu przejsciowego ("wysylka ... w przygotowaniu"), ktory Zadanie 11
    # usuwa z _sprawdz(). Po podmianie na atrape BL test sprawdza to samo co
    # zawsze mial sprawdzac - ze straznik PRZEPUSCIL zmiane (a nie odrzucil ja
    # komunikatem o rownoleglej edycji) - tyle ze teraz az do faktycznego
    # zapisu.
    id_zam, _ = dane
    with app.app_context():
        zam = SalesOrder.query.get(id_zam)
        zam.email = ''
        db.session.commit()
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'email', 'test@wp.pl',
                               bylo='')], ADMIN, klient_bl=AtrapaBL())
        assert wynik['wyniki'][0]['status'] == 'zapisane'
        assert SalesOrder.query.get(id_zam).email == 'test@wp.pl'


def test_endpoint_wymaga_wartosci_pierwotnej_w_kazdej_zmianie(app, dane, klient_http):
    id_zam, _ = dane
    odpowiedz = klient_http.post('/reports/api/arkusz/zapisz', json={'zmiany': [
        {'poziom': 'zamowienie', 'id': id_zam, 'nazwa': 'client_origin',
         'jest': 'Detal'}]})
    assert odpowiedz.status_code == 400
    assert 'pierwotnej' in odpowiedz.get_json()['komunikat']


# ===== zapis kolumn CRM ================================================

def test_blad_bazy_przy_zapisie_nie_wycieka_do_uzytkownika(app, dane, monkeypatch):
    # Surowy tekst wyjatku SQLAlchemy niesie cale zapytanie SQL razem
    # z parametrami (imie, adres, kwota) - wyciek struktury bazy
    # i komunikat, ktorego uzytkownik nie zrozumie (przeglad Zadania 10,
    # [WAZNE]). logger.error dwie linie wyzej juz zapisuje szczegoly.
    id_zam, _ = dane
    with app.app_context():
        def wybuchowy_commit():
            raise Exception(
                "UPDATE sales_orders SET client_origin=?, updated_at=? "
                "WHERE sales_orders.id = ? [parameters: ('Detal', ..., 1)]")
        monkeypatch.setattr(db.session, 'commit', wybuchowy_commit)

        wynik = zapisz([Zmiana('zamowienie', id_zam, 'client_origin', 'Detal')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        blad = wynik['wyniki'][0]['blad']
        assert 'UPDATE' not in blad
        assert 'sales_orders' not in blad
        assert 'administratorowi' in blad or 'spróbuj ponownie' in blad


def test_zapis_kolumny_crm_na_poziomie_zamowienia(app, dane):
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'client_origin', 'Stały B2B')], ADMIN)
        assert wynik['zapisane'] == 1
        assert wynik['wyniki'][0]['metoda'] is None
        assert SalesOrder.query.get(id_zam).client_origin == 'Stały B2B'


def test_zapis_kolumny_crm_na_poziomie_pozycji(app, dane):
    _, pozycje = dane
    with app.app_context():
        zapisz([Zmiana('pozycja', pozycje[0], 'wood_species', 'jesion')], ADMIN)
        assert SalesOrderItem.query.get(pozycje[0]).wood_species == 'jesion'


def test_zapis_scalonej_komorki_dotyka_tylko_zamowienia(app, dane):
    # Edycja scalonej komorki to JEDEN UPDATE na sales_orders, nie po jednym
    # na kazda pozycje pod spodem (spec 6.4).
    id_zam, pozycje = dane
    with app.app_context():
        przed = [SalesOrderItem.query.get(i).wood_species for i in pozycje]
        zapisz([Zmiana('zamowienie', id_zam, 'client_origin', 'Detal')], ADMIN)
        assert [SalesOrderItem.query.get(i).wood_species for i in pozycje] == przed


def test_pusta_wartosc_zapisuje_sie_jako_brak(app, dane):
    id_zam, _ = dane
    with app.app_context():
        zapisz([Zmiana('zamowienie', id_zam, 'client_origin', '')], ADMIN)
        assert SalesOrder.query.get(id_zam).client_origin is None


def test_kwota_liczba_data_i_flaga_trafiaja_we_wlasciwym_typie(app, dane):
    id_zam, pozycje = dane
    with app.app_context():
        zapisz([
            Zmiana('zamowienie', id_zam, 'paid_cash', '1338.36'),
            Zmiana('zamowienie', id_zam, 'own_transport', 'true'),
            Zmiana('pozycja', pozycje[0], 'thickness_cm', '2.7'),
        ], ADMIN)
        zam = SalesOrder.query.get(id_zam)
        assert zam.paid_cash == Decimal('1338.36')
        assert zam.own_transport is True
        assert SalesOrderItem.query.get(pozycje[0]).thickness_cm == Decimal('2.70')


def test_zapis_wymiaru_pozycji_przelicza_kolumny_wyliczane(app, dane):
    # thickness_cm jest w KOLUMNY_DOMYSLNE razem z total_volume
    # (arkusz_service.py). volume_per_piece/total_volume/total_surface_m2/
    # price_per_m3 sa kolumnami ZAPISANYMI, wypelnianymi przez ingest.py -
    # bez przeliczenia tutaj uzytkownik widzialby w wierszu nowa grubosc
    # i stara objetosc, a suma "TTL m3" w stopce zostawalaby bledna
    # (przeglad Zadania 10, [WAZNE]).
    _, pozycje = dane
    with app.app_context():
        poz = SalesOrderItem.query.get(pozycje[0])
        poz.length_cm = Decimal('100.00')
        poz.width_cm = Decimal('20.00')
        poz.quantity = 2
        db.session.commit()

        wynik = zapisz([Zmiana('pozycja', pozycje[0], 'thickness_cm', '5')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'zapisane', wynik['wyniki'][0].get('blad')

        poz = SalesOrderItem.query.get(pozycje[0])
        assert poz.thickness_cm == Decimal('5.00')
        # 1,00 m x 0,20 m x 0,05 m x 2 szt = 0,02 m3
        assert poz.volume_per_piece == Decimal('0.010000')
        assert poz.total_volume == Decimal('0.020000')
        # cena za m3 = wartosc netto (800.00, fixture) / objetosc TTL (0.02)
        assert poz.price_per_m3 == Decimal('40000.00')


def test_wynik_niesie_klucz_w_tym_samym_formacie_co_przegladarka(app, dane):
    # NIEZMIENNIK MIEDZYPANELOWY. arkusz.js buduje klucz jako
    # poziom + ':' + id + ':' + nazwa i po nim odnajduje komorke, gdy wraca
    # wynik. Rozjazd oznacza „zapisano" nad komorka, ktorej nikt nie zapisal.
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'client_origin', 'Detal')], ADMIN)
        assert wynik['wyniki'][0]['klucz'] == 'zamowienie:{}:client_origin'.format(id_zam)


def test_wynik_niesie_tekst_sformatowany_przez_serwer(app, dane):
    # Przegladarka nie formatuje liczb. Po zapisie komorka ma pokazac
    # „1 338,36", a nie „1338.36" wpisane przez uzytkownika.
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_cash', '1338.36')], ADMIN)
        assert wynik['wyniki'][0]['tekst'] == '1 338,36'


def test_wynik_niesie_tekst_zgodny_z_zaokragleniem_bazy(app, dane):
    # MySQL zaokragla decimal(10,2) w gore od polowki (ROUND_HALF_UP), a
    # domyslne formatowanie Decimal w Pythonie zaokragla do parzystej. Bez
    # kwantyzacji PRZED zapisem uzytkownik widzial np. "1,00" nad komorka,
    # w ktorej naprawde stalo 1,01 (przeglad Zadania 10, [WAZNE]).
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_cash', '1.005')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'zapisane', wynik['wyniki'][0].get('blad')
        assert wynik['wyniki'][0]['tekst'] == '1,01'
        assert SalesOrder.query.get(id_zam).paid_cash == Decimal('1.01')


# ===== uprawnienia rolowe ==============================================

def test_handlowiec_nie_moze_ruszyc_kolumny_z_baselinkera(app, dane):
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')],
                       HANDLOWIEC)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert 'administrator' in wynik['wyniki'][0]['blad']
        assert SalesOrder.query.get(id_zam).delivery_state == 'śląskie'


def test_handlowiec_moze_zapisac_kolumne_crm(app, dane):
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'client_origin', 'PH')], HANDLOWIEC)
        assert wynik['zapisane'] == 1
        assert SalesOrder.query.get(id_zam).client_origin == 'PH'


def test_pozycji_bez_identyfikatora_baselinkera_nie_da_sie_wyslac(app, dane):
    # Backfill nie przenosil bl_order_product_id, wiec 7938 pozycji
    # historycznych go nie ma, a setOrderProductFields bez niego nie zadziala.
    _, pozycje = dane
    with app.app_context():
        wynik = zapisz([Zmiana('pozycja', pozycje[1], 'quantity', '3')], ADMIN)
        assert wynik['wyniki'][0]['status'] == 'odrzucone'
        assert 'identyfikatora pozycji' in wynik['wyniki'][0]['blad']


# ===== endpoint ========================================================

@pytest.fixture()
def klient_http(app):
    from modules.users.services.permission_service import PermissionService
    oryginal = PermissionService.user_has_module_access
    PermissionService.user_has_module_access = staticmethod(lambda u, m: True)

    app.register_blueprint(reports_bp)
    app.add_url_rule('/login', 'login', lambda: 'login')
    pulpit = Blueprint('dashboard', __name__)
    pulpit.add_url_rule('/dashboard', 'dashboard', lambda: 'pulpit')
    app.register_blueprint(pulpit)
    app.jinja_loader = ChoiceLoader([
        DictLoader({'sidebar/sidebar.html': '<nav></nav>',
                    'access_denied.html': '<p>{{ module_name }}</p>'}),
        app.jinja_loader,
    ])
    with app.app_context():
        db.session.add(User(email='szef@woodpower.pl', password='x',
                            role='admin', active=True))
        db.session.commit()
    klient = app.test_client()
    with klient.session_transaction() as sesja:
        sesja['user_email'] = 'szef@woodpower.pl'
    yield klient
    PermissionService.user_has_module_access = oryginal


def test_endpoint_zapisu_odpowiada_200_i_wynikiem(app, dane, klient_http):
    id_zam, _ = dane
    odpowiedz = klient_http.post('/reports/api/arkusz/zapisz', json={'zmiany': [
        {'poziom': 'zamowienie', 'id': id_zam, 'nazwa': 'client_origin',
         'jest': 'Szablonowy', 'bylo': 'Sklep'}]})
    assert odpowiedz.status_code == 200
    dane_json = odpowiedz.get_json()
    assert dane_json['zapisane'] == 1
    assert dane_json['wyniki'][0]['status'] == 'zapisane'


def test_endpoint_zapisu_zwraca_400_z_komunikatem_po_polsku(klient_http):
    odpowiedz = klient_http.post('/reports/api/arkusz/zapisz', json={'zmiany': []})
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['error'] == 'zle_zmiany'
    assert odpowiedz.get_json()['komunikat']


def test_endpoint_zapisu_bez_ciala_zwraca_400_a_nie_500(klient_http):
    odpowiedz = klient_http.post('/reports/api/arkusz/zapisz',
                                 data='', content_type='application/json')
    assert odpowiedz.status_code == 400


def test_endpoint_zapisu_nie_odpowiada_na_get(klient_http):
    assert klient_http.get('/reports/api/arkusz/zapisz').status_code == 405


def test_endpoint_zapisu_zwraca_json_przy_wygaslej_sesji(klient_http):
    with klient_http.session_transaction() as sesja:
        sesja.clear()
    odpowiedz = klient_http.post('/reports/api/arkusz/zapisz', json={'zmiany': []})
    assert odpowiedz.status_code == 401
    assert odpowiedz.get_json() == {'error': 'unauthorized'}


# ===== WYSYLKA DO BASELINKERA (Zadanie 11) =============================

from modules.reports.bl_zapis import (  # noqa: E402
    KOLEJNOSC_METOD, BladBaselinkera, KlientBL, buduj_ladunek,
)


class AtrapaBL:
    """Zapamietuje wywolania zamiast strzelac do API. Zero ruchu sieciowego."""

    def __init__(self, bledy=None):
        self.wywolania = []
        self.bledy = bledy or {}      # metoda -> komunikat bledu

    def wyslij(self, metoda, ladunek):
        self.wywolania.append((metoda, ladunek))
        if metoda in self.bledy:
            raise BladBaselinkera(self.bledy[metoda])

    @property
    def metody(self):
        return [m for m, _ in self.wywolania]

    def ladunek(self, metoda):
        for m, l in self.wywolania:
            if m == metoda:
                return l
        return None


def test_kolejnosc_metod_jest_ustalona():
    assert KOLEJNOSC_METOD == ('setOrderFields', 'setOrderProductFields',
                               'setOrderPayment', 'setOrderStatus')


def test_wysylka_idzie_w_ustalonej_kolejnosci(app, dane):
    # Status ostatni, bo BaseLinker odpala na nim automatyzacje (etykiety,
    # faktury, powiadomienia) — maja zobaczyc juz poprawione dane.
    id_zam, pozycje = dane
    klient = AtrapaBL()
    with app.app_context():
        zapisz([
            Zmiana('zamowienie', id_zam, 'current_status', 'Odebrane'),
            Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00'),
            Zmiana('pozycja', pozycje[0], 'quantity', '3'),
            Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie'),
        ], ADMIN, klient_bl=klient)
    assert klient.metody == list(KOLEJNOSC_METOD)


def test_setorderfields_niesie_klucze_api_a_nie_nazwy_kolumn(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie'),
                Zmiana('zamowienie', id_zam, 'notes', 'Prosi o telefon')],
               ADMIN, klient_bl=klient)
    ladunek = klient.ladunek('setOrderFields')
    assert ladunek['order_id'] == 50854536
    assert ladunek['delivery_state'] == 'mazowieckie'
    assert ladunek['admin_comments'] == 'Prosi o telefon'
    assert 'notes' not in ladunek


def test_pola_dodatkowe_ida_w_custom_extra_fields(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zapisz([Zmiana('zamowienie', id_zam, 'caretaker', 'Ewa Fikcyjna')],
               ADMIN, klient_bl=klient)
    ladunek = klient.ladunek('setOrderFields')
    assert ladunek['custom_extra_fields'] == {'105623': 'Ewa Fikcyjna'}


def test_zaplacono_jest_przeliczane_na_brutto_dla_zamowienia_brutto(app, dane):
    # sales_orders.paid_amount trzyma kwote NETTO (tak mapowal backfill
    # i tak mapuje zapis przyrostowy). BaseLinker chce w payment_done kwoty,
    # ktora widzi klient. Bez przeliczenia wplata byla by zanizona o 23%,
    # a oplacone zamowienie zmienilo by sie w niedoplacone.
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        SalesOrder.query.get(id_zam).price_type = 'brutto'
        db.session.commit()
        zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')],
               ADMIN, klient_bl=klient)
    assert klient.ladunek('setOrderPayment')['payment_done'] == pytest.approx(1230.0)


def test_zaplacono_idzie_bez_przeliczenia_dla_zamowienia_netto(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        SalesOrder.query.get(id_zam).price_type = 'netto'
        db.session.commit()
        zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')],
               ADMIN, klient_bl=klient)
    assert klient.ladunek('setOrderPayment')['payment_done'] == pytest.approx(1000.0)


def test_platnosc_wysyla_kwote_i_date_razem(app, dane):
    # setOrderPayment PODMIENIA aktualna platnosc, nie dopisuje. Wyslanie
    # samej daty wyzerowaloby kwote.
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zam = SalesOrder.query.get(id_zam)
        zam.paid_amount = Decimal('500.00')
        zam.price_type = 'netto'
        db.session.commit()
        zapisz([Zmiana('zamowienie', id_zam, 'payment_date', '2026-09-18')],
               ADMIN, klient_bl=klient)
    ladunek = klient.ladunek('setOrderPayment')
    assert ladunek['payment_done'] == pytest.approx(500.0)
    assert isinstance(ladunek['payment_date'], int)


def test_data_platnosci_idzie_jako_unixtime(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zapisz([Zmiana('zamowienie', id_zam, 'payment_date', '2026-09-18')],
               ADMIN, klient_bl=klient)
    znacznik = klient.ladunek('setOrderPayment')['payment_date']
    from datetime import datetime as _dt
    assert _dt.fromtimestamp(znacznik).date() == date(2026, 9, 18)


def test_status_zamienia_sie_na_identyfikator(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zapisz([Zmiana('zamowienie', id_zam, 'current_status', 'Odebrane')],
               ADMIN, klient_bl=klient)
    assert klient.ladunek('setOrderStatus') == {'order_id': 50854536,
                                                'status_id': 149779}


def test_pozycja_idzie_z_identyfikatorem_pozycji(app, dane):
    _, pozycje = dane
    klient = AtrapaBL()
    with app.app_context():
        zapisz([Zmiana('pozycja', pozycje[0], 'price_gross', '1000.00')],
               ADMIN, klient_bl=klient)
    ladunek = klient.ladunek('setOrderProductFields')
    assert ladunek['order_id'] == 50854536
    assert ladunek['order_product_id'] == 991
    assert ladunek['price_brutto'] == pytest.approx(1000.0)


def test_zapis_lokalny_dopiero_po_potwierdzeniu_z_api(app, dane):
    # Spec 5.3 punkt 4. Klient, ktory zapamietuje stan bazy W MOMENCIE
    # wywolania — jesli kolumna jest juz zmieniona, zapis poszedl za wczesnie.
    id_zam, _ = dane
    stan_w_trakcie = {}

    class KlientSprawdzajacy(AtrapaBL):
        def wyslij(self, metoda, ladunek):
            stan_w_trakcie['delivery_state'] = SalesOrder.query.get(id_zam).delivery_state
            return super().wyslij(metoda, ladunek)

    with app.app_context():
        zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')],
               ADMIN, klient_bl=KlientSprawdzajacy())
        assert stan_w_trakcie['delivery_state'] == 'śląskie'
        assert SalesOrder.query.get(id_zam).delivery_state == 'mazowieckie'


def test_odrzucenie_przez_api_nie_zapisuje_lokalnie(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL(bledy={'setOrderFields': 'ERROR_ORDER_NOT_FOUND'})
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 1
        assert SalesOrder.query.get(id_zam).delivery_state == 'śląskie'


def test_komunikat_bledu_z_api_trafia_do_wyniku(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL(bledy={'setOrderFields': 'ERROR_ORDER_NOT_FOUND'})
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')],
                       ADMIN, klient_bl=klient)
        assert 'ERROR_ORDER_NOT_FOUND' in wynik['wyniki'][0]['blad']
        assert wynik['wyniki'][0]['metoda'] == 'setOrderFields'


def test_wszystkie_pola_jednego_wywolania_dziela_los(app, dane):
    # setOrderFields jest w BaseLinkerze atomowe: albo przeszlo wszystko,
    # albo nic. Wynik per pole musi to odzwierciedlac.
    id_zam, _ = dane
    klient = AtrapaBL(bledy={'setOrderFields': 'ERROR_AUTH'})
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie'),
                        Zmiana('zamowienie', id_zam, 'notes', 'cokolwiek')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 2
        assert all('ERROR_AUTH' in w['blad'] for w in wynik['wyniki'])


def test_porazka_jednej_metody_nie_blokuje_pozostalych(app, dane):
    # Makieta BladCzesciowy.dc.html: wojewodztwo przeszlo, zaplacono padlo.
    id_zam, _ = dane
    klient = AtrapaBL(bledy={'setOrderPayment': 'ERROR_ORDER_NOT_FOUND'})
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie'),
                        Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')],
                       ADMIN, klient_bl=klient)
        assert wynik['zapisane'] == 1 and wynik['odrzucone'] == 1
        zam = SalesOrder.query.get(id_zam)
        assert zam.delivery_state == 'mazowieckie'
        assert zam.paid_amount == Decimal('0.00')


def test_kolumny_crm_zapisuja_sie_mimo_porazki_baselinkera(app, dane):
    # Spec 5.3 punkt 2: kolumny CRM commituja sie NIEZALEZNIE od BL.
    id_zam, _ = dane
    klient = AtrapaBL(bledy={'setOrderFields': 'ERROR_AUTH'})
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'client_origin', 'Detal'),
                        Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')],
                       ADMIN, klient_bl=klient)
        assert wynik['zapisane'] == 1
        assert SalesOrder.query.get(id_zam).client_origin == 'Detal'


def test_zamowienie_bez_numeru_baselinkera_nie_jest_wysylane(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        SalesOrder.query.get(id_zam).baselinker_order_id = None
        db.session.commit()
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 1
        assert 'numeru zamówienia' in wynik['wyniki'][0]['blad']
        assert klient.wywolania == []


def test_wyjatek_sieciowy_konczy_sie_odrzuceniem_a_nie_piecsetka(app, dane):
    id_zam, _ = dane

    class KlientPadajacy:
        def wyslij(self, metoda, ladunek):
            raise RuntimeError('connection reset by peer')

    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')],
                       ADMIN, klient_bl=KlientPadajacy())
        assert wynik['odrzucone'] == 1
        assert 'connection reset' in wynik['wyniki'][0]['blad']


# ===== klient API ======================================================

def test_klient_bl_sklada_zadanie_zgodnie_z_api(monkeypatch):
    import modules.reports.bl_zapis as modul
    wyslane = {}

    class Odpowiedz:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {'status': 'SUCCESS'}

    def fałszywy_post(adres, headers=None, data=None, timeout=None):
        wyslane.update({'adres': adres, 'headers': headers, 'data': data})
        return Odpowiedz()

    monkeypatch.setattr(modul.requests, 'post', fałszywy_post)
    KlientBL(api_key='tajne', endpoint='https://api.baselinker.com/connector.php') \
        .wyslij('setOrderFields', {'order_id': 1, 'delivery_state': 'śląskie'})

    import json as _json
    assert wyslane['headers']['X-BLToken'] == 'tajne'
    assert wyslane['data']['method'] == 'setOrderFields'
    assert _json.loads(wyslane['data']['parameters'])['order_id'] == 1


def test_klient_bl_rozpoznaje_blad_zwrocony_przez_api(monkeypatch):
    import modules.reports.bl_zapis as modul

    class Odpowiedz:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {'status': 'ERROR', 'error_code': 'ERROR_ORDER_NOT_FOUND',
                    'error_message': 'Order not found'}

    monkeypatch.setattr(modul.requests, 'post',
                        lambda *a, **k: Odpowiedz())
    with pytest.raises(BladBaselinkera) as blad:
        KlientBL(api_key='tajne', endpoint='https://x').wyslij('setOrderFields', {})
    assert 'ERROR_ORDER_NOT_FOUND' in str(blad.value)


def test_brak_klucza_api_konczy_sie_czytelnym_bledem():
    with pytest.raises(BladBaselinkera) as blad:
        KlientBL(api_key=None, endpoint=None).wyslij('setOrderFields', {})
    assert 'konfiguracj' in str(blad.value)


def test_endpoint_uzywa_prawdziwego_klienta():
    # Zadanie 10 przekazywalo klient_bl=None jako stan przejsciowy.
    korzen = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(korzen, 'modules', 'reports', 'routers_analiza.py'),
              encoding='utf-8') as plik:
        zrodlo_tras = plik.read()
    assert 'klient_bl=None' not in zrodlo_tras
    assert 'klient_z_konfiguracji' in zrodlo_tras


# ===== PRZEGLAD ZADANIA 11 - POPRAWKI ==================================
# Kazda sekcja odpowiada jednemu znalezisku z przegladu. Test jest
# napisany tak, zeby PADAL na kodzie sprzed poprawki.

# --- [KRYTYCZNE] price_type jako wolny tekst mimo Enum('netto','brutto','') ---

def test_price_type_jest_wyborem_a_nie_wolnym_tekstem():
    from modules.reports.arkusz_service import kolumna_arkusza
    kolumna = kolumna_arkusza('price_type')
    assert kolumna['typ'] == 'wybor'
    assert set(kolumna['opcje']) == {'netto', 'brutto', ''}


def test_price_type_odrzuca_wartosc_spoza_enuma():
    # Dokladnie zmierzony w przegladzie scenariusz: 'gruszk' (6 znakow)
    # przechodzil walidacje dlugosci (limit Enuma) i szedl do BaseLinkera
    # jako custom_extra_fields, po czym commit do kolumny ENUM padal
    # LookupError-em przy kazdym kolejnym odczycie zamowienia.
    from modules.reports.arkusz_service import kolumna_arkusza
    from modules.reports.arkusz_zapis import na_wartosc
    with pytest.raises(ValueError) as blad:
        na_wartosc(kolumna_arkusza('price_type'), 'gruszk')
    assert 'gruszk' in str(blad.value)


def test_zapis_price_type_zlej_wartosci_nie_leci_do_baselinkera(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'price_type', 'gruszk')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 1
        assert SalesOrder.query.get(id_zam).price_type != 'gruszk'
    assert klient.wywolania == []


# --- [KRYTYCZNE] payment_date=0 (1970-01-01) gdy w bazie brak daty --------

def test_zaplacono_bez_daty_w_bazie_wysyla_dzisiejsza_a_nie_zero(app, dane):
    # Glowny scenariusz uzycia: zamowienie jeszcze nieoplacone
    # (payment_date IS NULL, tak ustawia je ingest.py) dostaje pierwsza
    # wplate. Stara wersja wysylala payment_date=0 (1970-01-01) —
    # sfabrykowana data, ktorej nikt nie wpisal.
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zam = SalesOrder.query.get(id_zam)
        assert zam.payment_date is None
        zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')],
               ADMIN, klient_bl=klient)
    ladunek = klient.ladunek('setOrderPayment')
    assert ladunek['payment_date'] != 0
    from datetime import datetime as _dt
    from modules.reports.analiza_service import dzis_lokalnie
    assert _dt.fromtimestamp(ladunek['payment_date']).date() == dzis_lokalnie()


def test_zaplacono_bez_daty_w_bazie_zapisuje_dzisiejsza_date_lokalnie(app, dane):
    # Spec: "te, ktora sie nie zmienila, bierzemy z bazy" - tu z bazy nie
    # ma czego wziac, wiec dzisiejsza data, ktora poszla do BaseLinkera,
    # MUSI wladowac tez do CRM-u, inaczej baza i BaseLinker sie rozjezdzaja.
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')],
               ADMIN, klient_bl=klient)
        from modules.reports.analiza_service import dzis_lokalnie
        assert SalesOrder.query.get(id_zam).payment_date == dzis_lokalnie()


def test_zaplacono_z_data_juz_w_bazie_nie_zmienia_daty(app, dane):
    # Kontrola: gdy baza JUZ MA date platnosci, poprawka nie ma jej
    # nadpisywac dzisiejsza.
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zam = SalesOrder.query.get(id_zam)
        zam.payment_date = date(2026, 1, 15)
        db.session.commit()
        zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')],
               ADMIN, klient_bl=klient)
        assert SalesOrder.query.get(id_zam).payment_date == date(2026, 1, 15)
    ladunek = klient.ladunek('setOrderPayment')
    from datetime import datetime as _dt
    assert _dt.fromtimestamp(ladunek['payment_date']).date() == date(2026, 1, 15)


# --- [KRYTYCZNE] quantity/price_gross nie przeliczaly kolumn pochodnych ---

def test_zmiana_ilosci_przez_bl_przelicza_wartosc_pozycji(app, dane):
    # Fixture: price_gross=984.00, value_net=800.00, qty=1 -> qty=5.
    # Bez poprawki value_net/value_gross zostawaly policzone dla 1 sztuki.
    _, pozycje = dane
    klient = AtrapaBL()
    with app.app_context():
        zapisz([Zmiana('pozycja', pozycje[0], 'quantity', '5')], ADMIN, klient_bl=klient)
        poz = SalesOrderItem.query.get(pozycje[0])
        assert poz.quantity == 5
        assert poz.price_net == Decimal('800.00')
        assert poz.value_gross == Decimal('4920.00')
        assert poz.value_net == Decimal('4000.00')


def test_zmiana_ceny_brutto_przez_bl_przelicza_cene_netto_pozycji(app, dane):
    # Dokladnie zmierzony w przegladzie scenariusz: price_gross 984.00 ->
    # 1230.00 zostawialo price_net na starych 800.00 zamiast nowych 1000.00.
    _, pozycje = dane
    klient = AtrapaBL()
    with app.app_context():
        zapisz([Zmiana('pozycja', pozycje[0], 'price_gross', '1230.00')],
               ADMIN, klient_bl=klient)
        poz = SalesOrderItem.query.get(pozycje[0])
        assert poz.price_gross == Decimal('1230.00')
        assert poz.price_net == Decimal('1000.00')
        assert poz.value_gross == Decimal('1230.00')
        assert poz.value_net == Decimal('1000.00')


def test_zmiana_ilosci_przez_bl_przelicza_objetosc_i_cene_za_m3(app, dane):
    # Scenariusz z przegladu: pozycja 100x50x4 cm, qty 1 -> 5. TTL m3 i
    # cena/m3 maja sie zmienic, nie zostac policzone dla jednej sztuki.
    _, pozycje = dane
    with app.app_context():
        poz = SalesOrderItem.query.get(pozycje[0])
        poz.length_cm, poz.width_cm, poz.thickness_cm = (
            Decimal('100'), Decimal('50'), Decimal('4'))
        db.session.commit()
        zapisz([Zmiana('pozycja', pozycje[0], 'quantity', '5')],
               ADMIN, klient_bl=AtrapaBL())
        poz = SalesOrderItem.query.get(pozycje[0])
        assert poz.total_volume == Decimal('0.100000')
        assert poz.price_per_m3 == Decimal('40000.00')


# --- [KRYTYCZNE] brak dolnej granicy: ujemna ilosc/wplata/koszt kuriera ---

@pytest.mark.parametrize('nazwa, wartosc, fragment', [
    ('paid_amount', '-1000.00', 'ujemn'),
    ('price_gross', '-50.00', 'ujemn'),
    ('delivery_cost', '-99.00', 'ujemn'),
    # `quantity` jest jedynym polem, ktore musi byc DODATNIE, wiec ujemna
    # i zerowa wartosc obie ida przez ten sam komunikat ("wieksza od zera").
    ('quantity', '-5', 'zera'),
    ('quantity', '0', 'zera'),
])
def test_konwersja_odrzuca_wartosc_ujemna_lub_zerowa_ilosc(nazwa, wartosc, fragment):
    from modules.reports.arkusz_service import kolumna_arkusza
    from modules.reports.arkusz_zapis import na_wartosc
    with pytest.raises(ValueError) as blad:
        na_wartosc(kolumna_arkusza(nazwa), wartosc)
    assert fragment in str(blad.value)


def test_ujemna_ilosc_nie_leci_do_baselinkera(app, dane):
    _, pozycje = dane
    klient = AtrapaBL()
    with app.app_context():
        wynik = zapisz([Zmiana('pozycja', pozycje[0], 'quantity', '-5')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 1
    assert klient.wywolania == []


def test_ujemna_wplata_nie_leci_do_baselinkera(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '-1000.00')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 1
        assert SalesOrder.query.get(id_zam).paid_amount == Decimal('0.00')
    assert klient.wywolania == []


# --- [WAZNE] _platnosc_brutto nie kwantyzowala do grosza -------------------

def test_platnosc_brutto_jest_zaokraglona_do_grosza():
    # 813.01 * 1.23 = 1000.0023 - bez kwantyzacji BaseLinker dostawal
    # wplate rozna od kwoty zamowienia o grosze.
    from modules.reports.bl_zapis import _platnosc_brutto
    assert _platnosc_brutto(Decimal('813.01'), 'brutto') == 1000.00


def test_zaplacono_brutto_w_zapisz_jest_zaokraglone_do_grosza(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zam = SalesOrder.query.get(id_zam)
        zam.price_type = 'brutto'
        db.session.commit()
        zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '813.01')],
               ADMIN, klient_bl=klient)
    assert klient.ladunek('setOrderPayment')['payment_done'] == 1000.00


# --- [WAZNE] blad zapisu lokalnego po BL ujawnial surowy wyjatek SQL ------

def test_blad_zapisu_lokalnego_po_bl_nie_ujawnia_szczegolow_sql(app, dane, monkeypatch):
    id_zam, _ = dane
    klient = AtrapaBL()

    def psuj_commit():
        raise Exception("UPDATE sales_orders SET delivery_state='x' WHERE id=1"
                        " -- SELECT haslo FROM users")

    with app.app_context():
        monkeypatch.setattr(db.session, 'commit', psuj_commit)
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')],
                       ADMIN, klient_bl=klient)
    assert wynik['odrzucone'] == 1
    blad = wynik['wyniki'][0]['blad']
    assert 'UPDATE sales_orders' not in blad
    assert 'haslo' not in blad
    assert 'Odśwież' in blad or 'odśwież' in blad.lower()


# --- [WAZNE] brak klient_bl konczyl sie angielskim AttributeError --------

def test_brak_klienta_bl_daje_czytelny_polski_komunikat_zamiast_attributeerror(app, dane):
    id_zam, _ = dane
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')],
                       ADMIN, klient_bl=None)
        assert wynik['odrzucone'] == 1
        blad = wynik['wyniki'][0]['blad']
        assert 'NoneType' not in blad
        assert 'attribute' not in blad
        assert SalesOrder.query.get(id_zam).delivery_state == 'śląskie'


# --- [WAZNE] angielskie wyjatki Pythona: puste "Ilosc", data "0001-01-01" -

def test_wyczyszczenie_ilosci_daje_czytelny_polski_komunikat():
    from modules.reports.arkusz_service import kolumna_arkusza
    from modules.reports.arkusz_zapis import na_wartosc
    with pytest.raises(ValueError) as blad:
        na_wartosc(kolumna_arkusza('quantity'), '')
    tekst = str(blad.value)
    assert 'NoneType' not in tekst
    assert 'puste' in tekst


def test_zapis_wyczyszczonej_ilosci_nie_wywala_wyjatku(app, dane):
    _, pozycje = dane
    klient = AtrapaBL()
    with app.app_context():
        wynik = zapisz([Zmiana('pozycja', pozycje[0], 'quantity', '')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 1
        assert 'NoneType' not in wynik['wyniki'][0]['blad']
    assert klient.wywolania == []


@pytest.mark.parametrize('data_tekst', ['0001-01-01', '1900-01-01', '9999-12-31'])
def test_data_platnosci_poza_sensownym_oknem_jest_odrzucana(data_tekst):
    from modules.reports.arkusz_service import kolumna_arkusza
    from modules.reports.arkusz_zapis import na_wartosc
    with pytest.raises(ValueError) as blad:
        na_wartosc(kolumna_arkusza('payment_date'), data_tekst)
    tekst = str(blad.value)
    assert 'year 0' not in tekst
    assert 'zakres' in tekst.lower()


def test_data_platnosci_ekstremalna_nie_leci_do_baselinkera(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'payment_date', '1900-01-01')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 1
    assert klient.wywolania == []


# --- [WAZNE] brak sanity-range na dacie platnosci (druga linia obrony) ---

def test_na_unixtime_odrzuca_date_poza_zakresem_jako_druga_linia_obrony():
    # Ta sama para granic, co w arkusz_zapis.na_wartosc, ale bezposrednio
    # w bl_zapis - na wypadek, gdyby cos ominelo walidacje wejscia (np.
    # dane wprost z bazy, nie z formularza).
    from modules.reports.bl_zapis import BladBaselinkera, _na_unixtime
    with pytest.raises(BladBaselinkera):
        _na_unixtime(date(1, 1, 1))
    with pytest.raises(BladBaselinkera):
        _na_unixtime(date(9999, 12, 31))
    # Data w rozsadnym oknie nadal dziala normalnie.
    assert _na_unixtime(date(2026, 9, 18)) > 0


# ===== DOMKNIECIE PLANU C: zapis platnosci do BaseLinkera ==============
# --- [KRYTYCZNE] brak typu ceny = kwota zawyzona o 23% -----------------

@pytest.mark.parametrize('typ_ceny', [None, '', '   '])
def test_platnosc_brutto_odrzuca_brak_typu_ceny(typ_ceny):
    # Stara wersja traktowala brak oznaczenia jak 'brutto' i mnozyla kwote
    # przez 1,23 NA DOMYSL. Odczyt tak liczyc moze (tak sa policzone dane
    # historyczne), ale zapis idzie do systemu, z ktorego ida faktury.
    from modules.reports.bl_zapis import BladBaselinkera, _platnosc_brutto
    with pytest.raises(BladBaselinkera):
        _platnosc_brutto(Decimal('1000.00'), typ_ceny)


@pytest.mark.parametrize('typ_ceny,oczekiwane', [
    ('brutto', 1230.00), ('BRUTTO', 1230.00), (' brutto ', 1230.00),
    ('netto', 1000.00), ('Netto', 1000.00),
])
def test_platnosc_brutto_przyjmuje_oznaczony_typ_ceny(typ_ceny, oczekiwane):
    # Kontrola do testu wyzej: odmowa dotyczy WYLACZNIE braku oznaczenia,
    # a nie wielkosci liter czy spacji dookola.
    from modules.reports.bl_zapis import _platnosc_brutto
    assert _platnosc_brutto(Decimal('1000.00'), typ_ceny) == oczekiwane


def test_zaplacono_bez_typu_ceny_nie_leci_do_baselinkera(app, dane):
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zam = SalesOrder.query.get(id_zam)
        zam.price_type = ''          # tak wyglada 3 zamowienia w bazie
        db.session.commit()
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 1 and wynik['zapisane'] == 0
        # Zadnego zapisu lokalnego: CRM nie moze pokazywac kwoty, ktorej
        # w BaseLinkerze nie ma.
        assert SalesOrder.query.get(id_zam).paid_amount == Decimal('0.00')
    assert klient.wywolania == []


def test_komunikat_o_braku_typu_ceny_mowi_co_zrobic(app, dane):
    # Komunikat ma powiedziec, co uzytkownik ma zrobic, a nie tylko ze sie
    # nie udalo. Etykieta kolumny leci z rejestru — ta sama, ktora widac
    # w naglowku arkusza.
    from modules.reports.fields import POLA
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        SalesOrder.query.get(id_zam).price_type = ''
        db.session.commit()
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')],
                       ADMIN, klient_bl=klient)
    blad = wynik['wyniki'][0]['blad']
    assert POLA['price_type'].etykieta in blad
    assert 'netto' in blad and 'brutto' in blad


def test_brak_typu_ceny_nie_blokuje_reszty_paczki(app, dane):
    # Odrzucenie zachowuje sie jak kazda inna porazka czesciowa: komorka
    # zostaje brudna, reszta paczki przechodzi normalnie.
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        SalesOrder.query.get(id_zam).price_type = ''
        db.session.commit()
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie'),
                        Zmiana('zamowienie', id_zam, 'client_origin', 'Detal'),
                        Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')],
                       ADMIN, klient_bl=klient)
        assert wynik['zapisane'] == 2 and wynik['odrzucone'] == 1
        zam = SalesOrder.query.get(id_zam)
        assert zam.delivery_state == 'mazowieckie'
        assert zam.client_origin == 'Detal'
        assert zam.paid_amount == Decimal('0.00')
    assert klient.metody == ['setOrderFields']


def test_typ_ceny_uzupelniony_w_tej_samej_paczce_przepuszcza_wplate(app, dane):
    # Komunikat kaze uzupelnic typ ceny — i ma to dzialac ZA JEDNYM RAZEM.
    # setOrderFields idzie w KOLEJNOSC_METOD przed setOrderPayment, wiec
    # 106169 jest juz zapisane, kiedy liczy sie payment_done.
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        SalesOrder.query.get(id_zam).price_type = ''
        db.session.commit()
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00'),
                        Zmiana('zamowienie', id_zam, 'price_type', 'netto')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 0 and wynik['zapisane'] == 2
        assert SalesOrder.query.get(id_zam).paid_amount == Decimal('1000.00')
    assert klient.ladunek('setOrderFields')['custom_extra_fields'] == {'106169': 'netto'}
    # Kluczowa liczba: netto, wiec BEZ mnozenia przez 1,23.
    assert klient.ladunek('setOrderPayment')['payment_done'] == pytest.approx(1000.0)


# --- [KRYTYCZNE] payment_date=0 (1970-01-01) po wyczyszczeniu komorki ---

def test_na_unixtime_odrzuca_brak_daty_zamiast_wysylac_zero():
    # Stare `return 0` to 1970-01-01 w BaseLinkerze — data, ktorej nikt
    # nie wpisal. setOrderPayment podmienia cala platnosc naraz, wiec
    # data jest WYMAGANA razem z kwota.
    from modules.reports.bl_zapis import BladBaselinkera, _na_unixtime
    with pytest.raises(BladBaselinkera):
        _na_unixtime(None)


def test_wyczyszczenie_daty_platnosci_nie_wysyla_1970(app, dane):
    # sales_orders.payment_date jest nullable, wiec pusta komorka przechodzi
    # walidacje jako None — i wracala do BaseLinkera jako payment_date=0.
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        zam = SalesOrder.query.get(id_zam)
        zam.payment_date = date(2026, 1, 15)
        zam.paid_amount = Decimal('500.00')
        db.session.commit()
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'payment_date', '')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 1
        # Data w CRM-ie zostaje nietknieta — zapis lokalny idzie DOPIERO
        # po potwierdzeniu z API.
        assert SalesOrder.query.get(id_zam).payment_date == date(2026, 1, 15)
    assert klient.wywolania == []


def test_wyczyszczenie_daty_razem_z_kwota_tez_nie_wysyla_1970(app, dane):
    # Obie kolumny siedza w tej samej grupie setOrderPayment, wiec dziela
    # jej los — kwota tez nie ma prawa pojsc z data 1970-01-01.
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        SalesOrder.query.get(id_zam).payment_date = date(2026, 1, 15)
        db.session.commit()
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'payment_date', ''),
                        Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')],
                       ADMIN, klient_bl=klient)
        assert wynik['odrzucone'] == 2 and wynik['zapisane'] == 0
        assert SalesOrder.query.get(id_zam).paid_amount == Decimal('0.00')
    assert klient.wywolania == []


# ===== FALA 3: ZAPIS SERWEROWY =========================================
# Znaleziska adwersaryjnego przegladu calej galezi "Analiza sprzedazowa".

# --- KRYTYCZNE 1: saldo po edycji skladnika ---------------------------

@pytest.fixture()
def dane_z_saldem(app, dane):
    """To samo zamowienie, ale z saldem policzonym POPRAWNIE na starcie.

    Fikstura `dane` zostawia balance_due=0.00 przy pozycjach na 1600 zl netto,
    wiec sama w sobie nie nadaje sie na punkt odniesienia dla "saldo przed
    i po". Tutaj ustawiamy je na wartosc zgodna ze wzorem z `ingest.py`:
    netto towarow (2 x 800) + kurier do zaplaty (123 brutto / 1,23) - wplata.
    """
    id_zam, pozycje = dane
    with app.app_context():
        zam = SalesOrder.query.get(id_zam)
        zam.delivery_cost = Decimal('123.00')
        zam.paid_amount = Decimal('0.00')
        zam.balance_due = Decimal('1700.00')
        db.session.commit()
    return id_zam, pozycje


@pytest.mark.parametrize('poziom, nazwa, wartosc, oczekiwane_saldo', [
    # Wplata 500 zl: 1600 + 100 - 500.
    ('zamowienie', 'paid_amount', '500.00', Decimal('1200.00')),
    # Kurier 246 brutto = 200 netto: 1600 + 200 - 0.
    ('zamowienie', 'delivery_cost', '246.00', Decimal('1800.00')),
    # Ilosc 2 na pierwszej pozycji: value_net 800 -> 1600, razem 2400 + 100.
    ('pozycja', 'quantity', '2', Decimal('2500.00')),
    # Cena brutto 1968 = 1600 netto na sztuke: 1600 + 800 = 2400, + 100.
    ('pozycja', 'price_gross', '1968.00', Decimal('2500.00')),
])
def test_edycja_skladnika_salda_przelicza_saldo(app, dane_z_saldem, poziom, nazwa,
                                                wartosc, oczekiwane_saldo):
    # Saldo jest ZAPISANA kolumna sales_orders, a nie wyliczana w locie —
    # bez przeliczenia tutaj kolumna "Saldo", kafelek KPI, kubelki naleznosci
    # i nadplaty pokazuja liczbe sprzed edycji.
    id_zam, pozycje = dane_z_saldem
    klient = AtrapaBL()
    identyfikator = id_zam if poziom == 'zamowienie' else pozycje[0]
    with app.app_context():
        saldo_przed = SalesOrder.query.get(id_zam).balance_due
        assert saldo_przed == Decimal('1700.00')
        wynik = zapisz([Zmiana(poziom, identyfikator, nazwa, wartosc)],
                       ADMIN, klient_bl=klient)
        assert wynik['zapisane'] == 1, wynik['wyniki']
        saldo_po = SalesOrder.query.get(id_zam).balance_due
    assert saldo_po != saldo_przed
    assert saldo_po == oczekiwane_saldo


def test_saldo_po_edycji_wlicza_pozycje_uslugowe(app, dane_z_saldem):
    # FALA 6. Saldo liczy sie ZE WSZYSTKICH pozycji, razem z usluga — tak sa
    # policzone dane lezace w bazie (zmierzone na woodpower_crm_local: wariant
    # z uslugami odtwarza SUM(balance_due) z dokladnoscia do 99,73 zl na
    # 732 tysiacach, wariant bez uslug rozjezdza sie o 82 695 zl) i tak jest
    # merytorycznie: za suszenie uslugowe klient tez jest nam winien.
    # Wykluczanie uslug zostaje WYLACZNIE w metrach szesciennych.
    # Trzeci wolajacy `ingest.oblicz_saldo` musi liczyc tak samo, co mapper
    # i upsert — inaczej saldo przesuwa sie w dniu pierwszej recznej edycji.
    id_zam, pozycje = dane_z_saldem
    klient = AtrapaBL()
    with app.app_context():
        SalesOrderItem.query.get(pozycje[1]).group_type = 'usługa'
        db.session.commit()
        zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '100.00')],
               ADMIN, klient_bl=klient)
        # 800 + 800 (takze usluga) + 100 kuriera netto - 100 wplaty.
        assert SalesOrder.query.get(id_zam).balance_due == Decimal('1600.00')


def test_zmiana_grupy_pozycji_nie_rusza_salda(app, dane_z_saldem):
    # "Grupa" jest kolumna CRM-owa, wiec idzie inna galezia zapisu niz wplata
    # i dalej WYZWALA przeliczenie salda (patrz `_POLA_SALDA_POZYCJI`) — ale
    # od fali 6 przeliczenie ma dac te sama liczbe, bo saldo nie zalezy juz
    # od grupy. Ten test pilnuje obu rzeczy naraz: galaz tylko-CRM zyje,
    # a przesuniecie pozycji do uslug nie zabiera z salda ani zlotowki.
    id_zam, pozycje = dane_z_saldem
    with app.app_context():
        wynik = zapisz([Zmiana('pozycja', pozycje[1], 'group_type', 'usługa')],
                       ADMIN)
        assert wynik['zapisane'] == 1, wynik['wyniki']
        assert SalesOrderItem.query.get(pozycje[1]).group_type == 'usługa'
        assert SalesOrder.query.get(id_zam).balance_due == Decimal('1700.00')


# --- KRYTYCZNE 2: poprawny JSON nie ma prawa dac 500 ------------------

@pytest.mark.parametrize('identyfikator', [float('inf'), float('-inf')])
def test_parsuj_odrzuca_nieskonczonosc_w_identyfikatorze(identyfikator):
    # `int(float('inf'))` rzuca OverflowError, ktorego stara wersja nie lapala.
    with pytest.raises(BladWalidacji):
        parsuj_zmiany({'zmiany': [{'poziom': 'zamowienie', 'id': identyfikator,
                                   'nazwa': 'client_origin', 'jest': 'x',
                                   'bylo': ''}]})


def test_endpoint_zapisu_z_nieskonczonym_id_zwraca_400_a_nie_500(klient_http):
    # {"id": 1e999} to POPRAWNY JSON — Flask parsuje go do float('inf').
    odpowiedz = klient_http.post(
        '/reports/api/arkusz/zapisz',
        data='{"zmiany": [{"poziom": "zamowienie", "id": 1e999, '
             '"nazwa": "client_origin", "jest": "x", "bylo": ""}]}',
        content_type='application/json')
    assert odpowiedz.status_code == 400
    assert odpowiedz.get_json()['komunikat']


@pytest.mark.parametrize('nazwa', [['client_origin'], {'a': 1}])
def test_parsuj_odrzuca_nazwe_kolumny_ktorej_nie_da_sie_odszukac(nazwa):
    # `nazwa not in POLA` na liscie/slowniku rzuca TypeError: unhashable type.
    with pytest.raises(BladWalidacji):
        parsuj_zmiany({'zmiany': [{'poziom': 'zamowienie', 'id': 1,
                                   'nazwa': nazwa, 'jest': 'x', 'bylo': ''}]})


def test_endpoint_zapisu_z_nazwa_kolumny_jako_lista_zwraca_400_a_nie_500(klient_http):
    odpowiedz = klient_http.post(
        '/reports/api/arkusz/zapisz',
        data='{"zmiany": [{"poziom": "zamowienie", "id": 1, '
             '"nazwa": ["client_origin"], "jest": "x", "bylo": ""}]}',
        content_type='application/json')
    assert odpowiedz.status_code == 400


# --- KRYTYCZNE 3: gorna granica kolumn calkowitych --------------------

@pytest.mark.parametrize('wartosc', ['99999999999', '2147483648'])
def test_konwersja_odrzuca_ilosc_poza_zakresem_kolumny_calkowitej(wartosc):
    from modules.reports.arkusz_service import kolumna_arkusza as opis
    from modules.reports.arkusz_zapis import na_wartosc
    with pytest.raises(ValueError) as blad:
        na_wartosc(opis('quantity'), wartosc)
    assert 'zakres' in str(blad.value)


def test_ilosc_poza_zakresem_kolumny_nie_leci_do_baselinkera(app, dane):
    # sales_order_items.quantity to INT — 99999999999 sie w nim nie miesci,
    # a bez gornej granicy przechodzil walidacje i szedl w
    # setOrderProductFields prosto do BaseLinkera.
    id_zam, pozycje = dane
    klient = AtrapaBL()
    with app.app_context():
        wynik = zapisz([Zmiana('pozycja', pozycje[0], 'quantity', '99999999999')],
                       ADMIN, klient_bl=klient)
    assert wynik['odrzucone'] == 1
    assert klient.wywolania == []


# --- WAZNE 4: ujemne wymiary pozycji ----------------------------------

@pytest.mark.parametrize('nazwa', ['length_cm', 'width_cm', 'thickness_cm'])
def test_konwersja_odrzuca_ujemny_wymiar_pozycji(nazwa):
    from modules.reports.arkusz_service import kolumna_arkusza as opis
    from modules.reports.arkusz_zapis import na_wartosc
    with pytest.raises(ValueError) as blad:
        na_wartosc(opis(nazwa), '-120')
    assert 'ujemn' in str(blad.value)


def test_ujemny_wymiar_nie_zapisuje_ujemnej_objetosci(app, dane):
    id_zam, pozycje = dane
    with app.app_context():
        wynik = zapisz([Zmiana('pozycja', pozycje[0], 'length_cm', '-120')], ADMIN)
        assert wynik['odrzucone'] == 1
        pozycja = SalesOrderItem.query.get(pozycje[0])
        assert pozycja.length_cm is None
        assert not (pozycja.total_volume or 0) < 0


# --- KRYTYCZNE 5: ladunek potwierdzenia mowi cala prawde ---------------

def test_potwierdzenie_wymienia_date_platnosci_imiennie(app, dane):
    # Edycja SAMEJ kolumny "Zaplacono" na zamowieniu z pustym payment_date
    # wysyla do BaseLinkera DZISIEJSZA date platnosci. Spec 5.3 pkt 1 chce,
    # zeby dialog wymienil kazde pole lecace do BL z nazwy.
    from modules.reports.arkusz_zapis import pozycje_potwierdzenia
    from modules.reports.analiza_service import dzis_lokalnie
    id_zam, _ = dane
    with app.app_context():
        pozycje = pozycje_potwierdzenia(
            [Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00')])
    nazwy = [p['nazwa'] for p in pozycje]
    assert 'payment_date' in nazwy
    wiersz = [p for p in pozycje if p['nazwa'] == 'payment_date'][0]
    assert wiersz['metoda'] == 'setOrderPayment'
    assert wiersz['dorozumiane'] is True
    assert wiersz['bedzie'] == dzis_lokalnie().strftime('%d.%m.%Y')


def test_potwierdzenie_wymienia_kwote_gdy_zmieniana_jest_sama_data(app, dane):
    # setOrderPayment podmienia cala platnosc naraz, wiec kwota z bazy tez
    # NAPRAWDE leci do BaseLinkera.
    from modules.reports.arkusz_zapis import pozycje_potwierdzenia
    id_zam, _ = dane
    with app.app_context():
        SalesOrder.query.get(id_zam).paid_amount = Decimal('500.00')
        db.session.commit()
        pozycje = pozycje_potwierdzenia(
            [Zmiana('zamowienie', id_zam, 'payment_date', '2026-09-20')])
    kwota = [p for p in pozycje if p['nazwa'] == 'paid_amount']
    assert len(kwota) == 1 and kwota[0]['dorozumiane'] is True


def test_potwierdzenie_nie_dubluje_pola_wpisanego_recznie(app, dane):
    from modules.reports.arkusz_zapis import pozycje_potwierdzenia
    id_zam, _ = dane
    with app.app_context():
        pozycje = pozycje_potwierdzenia([
            Zmiana('zamowienie', id_zam, 'paid_amount', '1000.00'),
            Zmiana('zamowienie', id_zam, 'payment_date', '2026-09-20')])
    assert [p['nazwa'] for p in pozycje].count('payment_date') == 1
    assert all(p['dorozumiane'] is False for p in pozycje)


def test_potwierdzenie_niesie_numer_zamowienia_pole_bylo_bedzie_i_metode(app, dane):
    from modules.reports.arkusz_zapis import pozycje_potwierdzenia
    id_zam, _ = dane
    with app.app_context():
        pozycje = pozycje_potwierdzenia(
            [Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')])
    assert pozycje == [{
        'klucz': 'zamowienie:{}:delivery_state'.format(id_zam),
        'zamowienie': 50854536, 'nazwa': 'delivery_state',
        'etykieta': 'Województwo', 'bylo': 'śląskie', 'bedzie': 'mazowieckie',
        'metoda': 'setOrderFields', 'dorozumiane': False,
    }]


def test_potwierdzenie_pomija_kolumny_ktore_nie_ida_do_baselinkera(app, dane):
    from modules.reports.arkusz_zapis import pozycje_potwierdzenia
    id_zam, _ = dane
    with app.app_context():
        pozycje = pozycje_potwierdzenia(
            [Zmiana('zamowienie', id_zam, 'client_origin', 'Szablonowy')])
    assert pozycje == []


# --- WAZNE 6: limit wywolan API na paczke ------------------------------

def test_limit_wywolan_bl_miesci_sie_pod_limitem_api_baselinkera():
    from modules.reports.arkusz_zapis import MAKS_WYWOLAN_BL
    # BaseLinker przyjmuje 100 zadan na minute na token; paczka ma sie
    # zmiescic w jednym zadaniu HTTP, a nie zablokowac workera na godziny.
    assert 0 < MAKS_WYWOLAN_BL <= 100


def test_paczka_ponad_limit_wywolan_nie_strzela_do_baselinkera(app, dane, monkeypatch):
    import modules.reports.arkusz_zapis as zapis_modul
    monkeypatch.setattr(zapis_modul, 'MAKS_WYWOLAN_BL', 2)
    klient = AtrapaBL()
    with app.app_context():
        zamowienia = []
        for numer in range(3):
            zam = SalesOrder(baselinker_order_id=90000 + numer,
                             date_created=date(2026, 9, 18), price_type='brutto',
                             paid_cash=Decimal('0.00'), paid_amount=Decimal('0.00'),
                             balance_due=Decimal('0.00'), own_transport=False,
                             picked_up=False)
            db.session.add(zam)
            db.session.flush()
            zamowienia.append(zam.id)
        db.session.commit()
        wynik = zapisz([Zmiana('zamowienie', i, 'current_status', 'Odebrane')
                        for i in zamowienia], ADMIN, klient_bl=klient)
    assert wynik['odrzucone'] == 3 and wynik['zapisane'] == 0
    assert klient.wywolania == []
    assert 'podziel' in wynik['wyniki'][0]['blad']


def test_limit_wywolan_nie_blokuje_kolumn_crm(app, dane, monkeypatch):
    # Limit dotyczy WYLACZNIE wysylki; kolumny tylko-CRM commituja sie
    # niezaleznie od BaseLinkera (spec 5.2).
    import modules.reports.arkusz_zapis as zapis_modul
    monkeypatch.setattr(zapis_modul, 'MAKS_WYWOLAN_BL', 0)
    id_zam, _ = dane
    klient = AtrapaBL()
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'client_origin', 'Szablonowy'),
                        Zmiana('zamowienie', id_zam, 'delivery_state', 'mazowieckie')],
                       ADMIN, klient_bl=klient)
        assert wynik['zapisane'] == 1 and wynik['odrzucone'] == 1
        assert SalesOrder.query.get(id_zam).client_origin == 'Szablonowy'
    assert klient.wywolania == []


# --- FALA 5: saldo ma JEDNA definicje, wspolna z ingest ---------------

def test_przeliczenie_salda_idzie_przez_wspolna_definicje(app, dane_z_saldem,
                                                          monkeypatch):
    # ZNALEZISKO KRYTYCZNE (fala 5): wzor salda byl przepisany w dwoch
    # miejscach (`ingest.mapuj_zamowienie` i `arkusz_zapis._przelicz_saldo`)
    # i dla zamowienia z wierszem-dziedzictwem dawal DWIE rozne liczby.
    # Ten test pilnuje, ze po stronie arkusza nie ma juz wlasnej arytmetyki:
    # podmiana wspolnej funkcji musi zmienic wynik zapisu.
    from modules.reports import arkusz_zapis

    id_zam, _ = dane_z_saldem
    monkeypatch.setattr(arkusz_zapis, 'saldo_z_wierszy',
                        lambda zamowienie: Decimal('4242.00'))
    with app.app_context():
        wynik = zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '500.00')],
                       ADMIN, klient_bl=AtrapaBL())
        assert wynik['zapisane'] == 1, wynik['wyniki']
        assert SalesOrder.query.get(id_zam).balance_due == Decimal('4242.00'), \
            'arkusz liczy saldo wlasnym wzorem zamiast wspolna definicja'


def test_saldo_z_arkusza_liczy_sie_z_wierszy_w_bazie(app, dane_z_saldem):
    # Druga strona tego samego rozstrzygniecia: zbiorem pozycji sa WIERSZE
    # w bazie, wiec dolozenie wiersza-dziedzictwa (bez `bl_order_product_id`,
    # czyli tak, jak zostawil je backfill) zmienia saldo po edycji.
    # Uzasadnienie wyboru: `ingest.saldo_z_wierszy`.
    id_zam, _ = dane_z_saldem
    with app.app_context():
        db.session.add(SalesOrderItem(order_id=id_zam, bl_order_product_id=None,
                                      wood_species='dąb', quantity=1,
                                      price_gross=Decimal('984.00'),
                                      value_net=Decimal('800.00')))
        db.session.commit()

        zapisz([Zmiana('zamowienie', id_zam, 'paid_amount', '100.00')],
               ADMIN, klient_bl=AtrapaBL())
        # 3 x 800 netto + 100 kuriera netto - 100 wplaty.
        assert SalesOrder.query.get(id_zam).balance_due == Decimal('2400.00')


# ===== ZMIANA STATUSU A SPRZEDAŻ (partia E, punkt E5) ===================

def test_zmiana_statusu_w_arkuszu_przestawia_identyfikator_i_liczniki_klienta(app, dane):
    """Warunek „tylko sprzedaż" rozpoznaje zamówienia anulowane i nieopłacone
    po `baselinker_status_id`. Zmiana statusu wysłana z Arkusza zapisywała
    dotąd samą NAZWĘ — identyfikator zostawał stary, więc zamówienie
    anulowane w Arkuszu liczyło się do sprzedaży aż do kolejnej
    synchronizacji. Razem z identyfikatorem przelicza się klient: jego
    `orders_count` i `lifetime_net` liczą wyłącznie sprzedaż."""
    id_zam, _ = dane
    with app.app_context():
        klient = SalesClient(display_name='Jan Przykładowy', orders_count=1,
                             lifetime_net=Decimal('1600.00'),
                             first_order_at=date(2026, 9, 18),
                             last_order_at=date(2026, 9, 18))
        db.session.add(klient)
        db.session.flush()
        zamowienie = SalesOrder.query.get(id_zam)
        zamowienie.client_id = klient.id
        zamowienie.current_status = 'Nowe - opłacone'
        zamowienie.baselinker_status_id = 155824
        id_klienta = klient.id
        db.session.commit()

        zapisz([Zmiana('zamowienie', id_zam, 'current_status', 'Zamówienie anulowane')],
               ADMIN, klient_bl=AtrapaBL())
        db.session.expire_all()
        assert SalesOrder.query.get(id_zam).baselinker_status_id == 138625
        klient = SalesClient.query.get(id_klienta)
        assert (klient.orders_count, klient.lifetime_net, klient.first_order_at) == (
            0, Decimal('0.00'), None)

        zapisz([Zmiana('zamowienie', id_zam, 'current_status', 'Nowe - opłacone')],
               ADMIN, klient_bl=AtrapaBL())
        db.session.expire_all()
        assert SalesOrder.query.get(id_zam).baselinker_status_id == 155824
        klient = SalesClient.query.get(id_klienta)
        assert (klient.orders_count, klient.lifetime_net, klient.first_order_at) == (
            1, Decimal('1600.00'), date(2026, 9, 18))
