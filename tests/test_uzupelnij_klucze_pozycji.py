# -*- coding: utf-8 -*-
"""Skrypt jednorazowy: uzupełnia `bl_order_product_id` wierszom
`sales_order_items`, które go nie mają, dopasowując je do pozycji
z BaseLinkera.

RYZYKO, KTÓRE TEN SKRYPT MA ROZBROIĆ. Po dodaniu ograniczenia
UNIQUE(order_id, bl_order_product_id) (migracja
2026-09-23-unikalnosc-klucza-pozycji.sql) `_upsert_pozycje`
(modules/reports/ingest.py) dalej dopasowuje pozycje WYŁĄCZNIE po kluczu —
wiersz-dziedzictwo bez klucza NIGDY nie dopasuje się do przysyłki z BL, więc
ten sam produkt przyjdzie jako NOWY wiersz. Ten skrypt ma domknąć tę lukę
RAZ, pod kontrolą człowieka, zanim pierwsza kolejna synchronizacja zdąży
zdublować pozycje z trzymiesięcznego okna.

DOPASOWANIE JEST ZGADYWANIEM — stąd domyślny tryb próby. Sygnatura
(nazwa produktu, ilość, cena netto) nie jest kluczem obcym: gdy w JEDNYM
zamówieniu dwie pozycje mają identyczną sygnaturę, nie da się jednoznacznie
rozstrzygnąć, KTÓRA odpowiada któremu `bl_order_product_id` — taki przypadek
zostaje NIETKNIĘTY (klasyfikacja „niejednoznaczne"), nawet w trybie zapisu.

Wzorzec: tests/test_sales_uzupelnianie.py (skrypt jednorazowy, ten sam
fixture bazy) i scripts/backfill_sales_tables.py (liczniki, raport,
odmowa przy niespójności).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

# Import czegokolwiek z modules.reports wykonuje modules/reports/__init__.py,
# który rejestruje cały graf modeli — ten sam gotcha i to samo rozwiązanie
# co w tests/test_sales_backfill.py i tests/test_sales_uzupelnianie.py.
from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
from uzupelnij_klucze_pozycji import (  # noqa: E402
    OKNO_DNI, dopasuj_pozycje_zamowienia, przetworz_wszystkie,
    zbierz_kandydatow,
)

_TABLES = [m.__table__ for m in (SalesClient, SalesOrder, SalesOrderItem)]


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


def zamowienie_db(bl_id=555, dni_temu=10, **nadpisania):
    # Ten sam „dziś", od którego skrypt liczy okno (`dzis_lokalnie()`, czas
    # polski), a nie `date.today()` kontenera w UTC.
    from datetime import timedelta
    from modules.reports.analiza_service import dzis_lokalnie
    baza = dict(baselinker_order_id=bl_id,
                date_created=dzis_lokalnie() - timedelta(days=dni_temu))
    baza.update(nadpisania)
    z = SalesOrder(**baza)
    db.session.add(z)
    db.session.flush()
    return z


def pozycja_db(zamowienie, nazwa='Blat dębowy A', ilosc=1, cena=Decimal('100.00'),
               klucz=None):
    p = SalesOrderItem(order_id=zamowienie.id, raw_product_name=nazwa,
                       quantity=ilosc, price_net=cena, bl_order_product_id=klucz)
    db.session.add(p)
    db.session.flush()
    return p


def produkt_bl(order_product_id, nazwa='Blat dębowy A', ilosc=1, cena_netto='100.00'):
    """Pozycja w kształcie, jaki zwraca `mapuj_pozycje` (ingest.py) —
    tylko pola, których dopasowanie faktycznie używa."""
    return {
        'bl_order_product_id': order_product_id,
        'raw_product_name': nazwa,
        'quantity': ilosc,
        'price_net': Decimal(cena_netto),
    }


# ===== dopasuj_pozycje_zamowienia (funkcja czysta) =====================

def test_jednoznaczne_dopasowanie_pojedynczej_pozycji(app):
    with app.app_context():
        z = zamowienie_db()
        w = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))

        dopasowania, niejednoznaczne, bez_dopasowania = dopasuj_pozycje_zamowienia(
            [w], [produkt_bl(991, 'Blat A', 1, '100.00')])

        assert dopasowania == [(w, 991)]
        assert niejednoznaczne == []
        assert bez_dopasowania == []


def test_rozna_cena_w_sygnaturze_nie_dopasowuje_sie(app):
    """Sygnatura obejmuje cenę: sama zgodność nazwy i ilości nie wystarcza —
    inna cena netto to dla dopasowania INNY produkt (np. zmieniona wycena)."""
    with app.app_context():
        z = zamowienie_db()
        w = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))

        dopasowania, niejednoznaczne, bez_dopasowania = dopasuj_pozycje_zamowienia(
            [w], [produkt_bl(991, 'Blat A', 1, '150.00')])

        assert dopasowania == []
        assert niejednoznaczne == []
        assert bez_dopasowania == [w]


def test_brak_kandydata_bl_daje_bez_dopasowania(app):
    with app.app_context():
        z = zamowienie_db()
        w = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))

        dopasowania, niejednoznaczne, bez_dopasowania = dopasuj_pozycje_zamowienia(
            [w], [produkt_bl(991, 'Blat INNY', 1, '100.00')])

        assert dopasowania == []
        assert niejednoznaczne == []
        assert bez_dopasowania == [w]


def test_dwie_identyczne_sygnatury_sa_niejednoznaczne(app):
    """Rdzeń bezpieczeństwa: gdy sygnatura nie rozstrzyga jednoznacznie,
    skrypt MA NIE ZGADYWAĆ, nawet jeśli liczba kandydatów po obu stronach
    się zgadza."""
    with app.app_context():
        z = zamowienie_db()
        w1 = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))
        w2 = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))

        dopasowania, niejednoznaczne, bez_dopasowania = dopasuj_pozycje_zamowienia(
            [w1, w2], [produkt_bl(991, 'Blat A', 1, '100.00'),
                      produkt_bl(992, 'Blat A', 1, '100.00')])

        assert dopasowania == []
        assert set(niejednoznaczne) == {w1, w2}
        assert bez_dopasowania == []


def test_wiecej_kandydatow_bl_niz_wierszy_db_jest_niejednoznaczne(app):
    with app.app_context():
        z = zamowienie_db()
        w = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))

        dopasowania, niejednoznaczne, bez_dopasowania = dopasuj_pozycje_zamowienia(
            [w], [produkt_bl(991, 'Blat A', 1, '100.00'),
                  produkt_bl(992, 'Blat A', 1, '100.00')])

        assert dopasowania == []
        assert niejednoznaczne == [w]
        assert bez_dopasowania == []


def test_rozne_sygnatury_w_tym_samym_zamowieniu_dopasowuja_sie_niezaleznie(app):
    with app.app_context():
        z = zamowienie_db()
        w1 = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))
        w2 = pozycja_db(z, nazwa='Blat B', ilosc=2, cena=Decimal('50.00'))

        dopasowania, niejednoznaczne, bez_dopasowania = dopasuj_pozycje_zamowienia(
            [w1, w2], [produkt_bl(991, 'Blat A', 1, '100.00'),
                      produkt_bl(992, 'Blat B', 2, '50.00')])

        assert set(dopasowania) == {(w1, 991), (w2, 992)}
        assert niejednoznaczne == []
        assert bez_dopasowania == []


def test_cena_zaokraglona_inaczej_ale_ta_sama_wartosc_nadal_sie_dopasowuje(app):
    with app.app_context():
        z = zamowienie_db()
        w = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))
        # BL bywa float -> Decimal('100.0') po drodze, nie 'Decimal(100.00)'
        # co do skali — dopasowanie ma porównywać WARTOŚĆ, nie reprezentację.
        pozycja = produkt_bl(991, 'Blat A', 1, '100.0')
        pozycja['price_net'] = Decimal('100.0')

        dopasowania, _, _ = dopasuj_pozycje_zamowienia([w], [pozycja])
        assert dopasowania == [(w, 991)]


# ===== zbierz_kandydatow (zapytanie o okno) =============================

def test_zbiera_tylko_zamowienia_z_baselinker_id_w_oknie_i_z_brakiem_klucza(app):
    with app.app_context():
        z1 = zamowienie_db(bl_id=1, dni_temu=10)
        pozycja_db(z1, klucz=None)

        # poza oknem (starsze niz OKNO_DNI)
        z2 = zamowienie_db(bl_id=2, dni_temu=OKNO_DNI + 5)
        pozycja_db(z2, klucz=None)

        # w oknie, ale bez numeru BL (nie da się dociągnąć zamówienia)
        z3 = zamowienie_db(bl_id=None, dni_temu=5)
        pozycja_db(z3, klucz=None)

        # w oknie, z numerem BL, ale WSZYSTKIE pozycje już mają klucz
        z4 = zamowienie_db(bl_id=4, dni_temu=5)
        pozycja_db(z4, klucz=123)

        db.session.commit()

        kandydaci = zbierz_kandydatow()
        assert [z.id for z in kandydaci] == [z1.id]


# ===== przetworz_wszystkie (pętla + tryb próby vs zapis) =================

def _pobierz_z_mapy(mapa):
    def pobierz(bl_order_id):
        return mapa.get(bl_order_id)
    return pobierz


def test_tryb_proby_nie_zapisuje_nic_do_bazy(app):
    with app.app_context():
        z = zamowienie_db(bl_id=555)
        w = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))
        db.session.commit()

        pobierz = _pobierz_z_mapy({555: {'products': [
            {'order_product_id': 991, 'name': 'Blat A', 'quantity': 1,
             'price_brutto': 123.0}]}})

        statystyki, niejednoznaczne = przetworz_wszystkie(
            [z], pobierz, zapisz=False)

        assert statystyki['pozycji_jednoznacznych'] == 1
        # Tryb próby: baza NIETKNIĘTA, mimo jednoznacznego dopasowania.
        assert SalesOrderItem.query.get(w.id).bl_order_product_id is None


def test_tryb_zapisu_uzupelnia_wylacznie_jednoznaczne(app):
    with app.app_context():
        z = zamowienie_db(bl_id=555)
        w_ok = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))
        w_ok2 = pozycja_db(z, nazwa='Blat B', ilosc=1, cena=Decimal('50.00'))
        w_niejedno_1 = pozycja_db(z, nazwa='Blat X', ilosc=1, cena=Decimal('10.00'))
        w_niejedno_2 = pozycja_db(z, nazwa='Blat X', ilosc=1, cena=Decimal('10.00'))
        db.session.commit()

        pobierz = _pobierz_z_mapy({555: {'products': [
            {'order_product_id': 991, 'name': 'Blat A', 'quantity': 1, 'price_brutto': 123.0},
            {'order_product_id': 992, 'name': 'Blat B', 'quantity': 1, 'price_brutto': 61.5},
            {'order_product_id': 993, 'name': 'Blat X', 'quantity': 1, 'price_brutto': 12.3},
            {'order_product_id': 994, 'name': 'Blat X', 'quantity': 1, 'price_brutto': 12.3},
        ]}})

        statystyki, niejednoznaczne = przetworz_wszystkie(
            [z], pobierz, zapisz=True)

        assert statystyki['pozycji_jednoznacznych'] == 2
        assert statystyki['pozycji_niejednoznacznych'] == 2
        assert SalesOrderItem.query.get(w_ok.id).bl_order_product_id is not None
        assert SalesOrderItem.query.get(w_ok2.id).bl_order_product_id is not None
        assert SalesOrderItem.query.get(w_niejedno_1.id).bl_order_product_id is None
        assert SalesOrderItem.query.get(w_niejedno_2.id).bl_order_product_id is None
        assert len(niejednoznaczne) == 2


def test_juz_uzyty_klucz_w_bazie_nie_jest_ponownie_przydzielany(app):
    """Wiersz, który JUŻ MA klucz, jest wykluczony z puli kandydatów BL —
    inaczej dwa wiersze tego samego zamówienia mogłyby dostać ten sam klucz
    i złamać dopiero co dodane ograniczenie UNIQUE."""
    with app.app_context():
        z = zamowienie_db(bl_id=555)
        juz_ma_klucz = pozycja_db(z, nazwa='Blat A', ilosc=1,
                                  cena=Decimal('100.00'), klucz=991)
        bez_klucza = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))
        db.session.commit()

        # BaseLinker przysyła TĘ SAMĄ pozycję (991) plus nic innego pasującego
        # do sygnatury — bez_klucza ma zostać bez dopasowania, nie dostać
        # cudzego (już zajętego) klucza.
        pobierz = _pobierz_z_mapy({555: {'products': [
            {'order_product_id': 991, 'name': 'Blat A', 'quantity': 1, 'price_brutto': 123.0},
        ]}})

        statystyki, _ = przetworz_wszystkie([z], pobierz, zapisz=True)

        assert statystyki['pozycji_bez_dopasowania'] == 1
        assert SalesOrderItem.query.get(juz_ma_klucz.id).bl_order_product_id == 991
        assert SalesOrderItem.query.get(bez_klucza.id).bl_order_product_id is None


def test_zamowienie_bez_odpowiedzi_z_baselinkera_jest_pomijane_bez_bledu(app):
    with app.app_context():
        z = zamowienie_db(bl_id=555)
        pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))
        db.session.commit()

        pobierz = _pobierz_z_mapy({})  # BaseLinker nie zwrócił nic

        statystyki, niejednoznaczne = przetworz_wszystkie([z], pobierz, zapisz=True)

        assert statystyki['zamowien_bez_danych_bl'] == 1
        assert statystyki['pozycji_jednoznacznych'] == 0


def test_skrypt_jest_idempotentny_drugi_przebieg_nie_rusza_juz_uzupelnionych(app):
    with app.app_context():
        z = zamowienie_db(bl_id=555)
        w = pozycja_db(z, nazwa='Blat A', ilosc=1, cena=Decimal('100.00'))
        db.session.commit()

        pobierz = _pobierz_z_mapy({555: {'products': [
            {'order_product_id': 991, 'name': 'Blat A', 'quantity': 1, 'price_brutto': 123.0},
        ]}})

        przetworz_wszystkie([z], pobierz, zapisz=True)
        assert SalesOrderItem.query.get(w.id).bl_order_product_id == 991

        # Drugi przebieg: zbierz_kandydatow już nie znajdzie tego zamówienia,
        # bo nie ma już wiersza bez klucza — symulujemy to samo wywołaniem
        # zbierz_kandydatow zamiast ręcznego [z].
        kandydaci = zbierz_kandydatow()
        assert kandydaci == []


def test_niejednoznaczne_pozostaja_niejednoznaczne_przy_ponownym_przebiegu(app):
    """Wiersze bez rozstrzygnięcia NIE dostają klucza nigdy — drugi przebieg
    ma je zgłosić identycznie jak pierwszy, bo `zbierz_kandydatow` dalej
    widzi je jako `bez_klucza`."""
    with app.app_context():
        z = zamowienie_db(bl_id=555)
        pozycja_db(z, nazwa='Blat X', ilosc=1, cena=Decimal('10.00'))
        pozycja_db(z, nazwa='Blat X', ilosc=1, cena=Decimal('10.00'))
        db.session.commit()

        pobierz = _pobierz_z_mapy({555: {'products': [
            {'order_product_id': 993, 'name': 'Blat X', 'quantity': 1, 'price_brutto': 12.3},
            {'order_product_id': 994, 'name': 'Blat X', 'quantity': 1, 'price_brutto': 12.3},
        ]}})

        pierwszy, _ = przetworz_wszystkie(zbierz_kandydatow(), pobierz, zapisz=True)
        drugi, _ = przetworz_wszystkie(zbierz_kandydatow(), pobierz, zapisz=True)

        assert pierwszy['pozycji_niejednoznacznych'] == 2
        assert drugi['pozycji_niejednoznacznych'] == 2


# ===== main() / CLI ======================================================

def test_domyslny_tryb_to_proba_bez_flagi_zapisz():
    from uzupelnij_klucze_pozycji import zbuduj_parser
    args = zbuduj_parser().parse_args([])
    assert args.zapisz is False


def test_flaga_zapisz_wlacza_tryb_zapisu():
    from uzupelnij_klucze_pozycji import zbuduj_parser
    args = zbuduj_parser().parse_args(['--zapisz'])
    assert args.zapisz is True


# --- tempo zapytań i bezpiecznik blokady (24.09.2026) -----------------------
# Pierwszy przebieg na produkcji bez odstępu przekroczył limit 100 zapytań/min
# i BaseLinker zablokował API CAŁEGO konta. Te testy pilnują, że skrypt czeka
# między zapytaniami i po komunikacie o limicie przestaje pytać.

def test_pobieracz_czeka_miedzy_zapytaniami():
    from scripts.uzupelnij_klucze_pozycji import pobieracz_z_limitem
    drzemki = []
    pobierz = pobieracz_z_limitem(
        lambda bl_id: {'status': 'SUCCESS', 'orders': [{'order_id': bl_id}]},
        odstep_s=1.0, spij=drzemki.append)
    assert [pobierz(i)['order_id'] for i in (1, 2, 3)] == [1, 2, 3]
    assert drzemki == [1.0, 1.0]   # przed 2. i 3., nie przed pierwszym


def test_pobieracz_po_blokadzie_przestaje_pytac():
    from scripts.uzupelnij_klucze_pozycji import pobieracz_z_limitem
    wywolania = []

    def zapytanie(bl_id):
        wywolania.append(bl_id)
        if bl_id == 2:
            return {'status': 'ERROR', 'error_code': 'ERROR_API_LIMIT',
                    'error_message': 'Query limit exceeded'}
        return {'status': 'SUCCESS', 'orders': [{'order_id': bl_id}]}

    pobierz = pobieracz_z_limitem(zapytanie, odstep_s=0, spij=lambda s: None)
    wyniki = [pobierz(i) for i in (1, 2, 3, 4)]
    assert wyniki[0] == {'order_id': 1}
    assert wyniki[1:] == [None, None, None]
    assert wywolania == [1, 2]          # 3 i 4 NIE poszły do API
    assert pobierz.blokada is True
    assert pobierz.pominiete_po_blokadzie == 2


def test_pobieracz_zwykly_blad_nie_zatrzymuje_przebiegu():
    from scripts.uzupelnij_klucze_pozycji import pobieracz_z_limitem
    wywolania = []

    def zapytanie(bl_id):
        wywolania.append(bl_id)
        return ({'status': 'ERROR', 'error_code': 'ERROR_ORDER_NOT_FOUND'}
                if bl_id == 1 else {'status': 'SUCCESS', 'orders': []})

    pobierz = pobieracz_z_limitem(zapytanie, odstep_s=0, spij=lambda s: None)
    assert [pobierz(i) for i in (1, 2)] == [None, None]
    assert wywolania == [1, 2] and pobierz.blokada is False
