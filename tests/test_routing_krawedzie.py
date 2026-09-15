# -*- coding: utf-8 -*-
"""
Trasa produktu po podziale Wykańczania na Krawędzie i Lakiernię.

Dziś ŻADEN test nie woła ProductionProduct.complete_task dla wykańczania ani
lakierni — cały routing jest pokryty pośrednio, przez order_timeline_service,
który ma WŁASNĄ kopię reguły. Ten plik pokrywa cztery ścieżki produktu wprost
na modelu:

    surowy bez krawędzi            → logistyka
    olej/lakier bez krawędzi       → Lakiernia → logistyka     (NOWA GAŁĄŹ)
    surowy z krawędziami           → Krawędzie → logistyka
    olej/lakier z krawędziami      → Krawędzie → Lakiernia → logistyka

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionWorker,
)
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABELE = [m.__table__ for m in (
    User, ProductionDevice, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionStationEvent,
    ProductionReworkLog,
)]

# LONGTEXT nie istnieje w SQLite — ten sam zabieg co w tests/test_worker_stats.py.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()


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
        db.metadata.create_all(bind=db.engine, tables=_TABELE)
        yield app
        db.session.remove()


_licznik = itertools.count(1)


def _produkt(finish='surowe', edge=False, cut_to_size=True, quantity=10,
             status='czeka_na_formatowanie', odbior_osobisty=False):
    """Produkt z zamówieniem kurierskim (albo do odbioru osobistego).

    Adres, miasto i kod pocztowy są obowiązkowe dla wariantu kurierskiego:
    ProductionOrder.is_personal_pickup (models.py:171-183) uznaje zamówienie
    BEZ żadnego z tych pól za odbiór osobisty, co po cichu zamieniłoby
    logistykę na pakowanie w każdym teście trasy.
    """
    numer = next(_licznik)
    if odbior_osobisty:
        zamowienie = ProductionOrder(
            baselinker_order_id=numer,
            internal_order_number='26/%05d' % numer,
            delivery_method='Odbiór osobisty')
    else:
        zamowienie = ProductionOrder(
            baselinker_order_id=numer,
            internal_order_number='26/%05d' % numer,
            delivery_method='Kurier DPD',
            delivery_address='ul. Testowa 1',
            delivery_city='Warszawa',
            delivery_postcode='00-001')
    db.session.add(zamowienie)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=zamowienie.id,
        short_product_id='26%03d_1' % numer,
        product_sequence_in_order=1,
        original_product_name='Blat dębowy',
        quantity=quantity,
        current_status=status,
        parsed_finish_type=finish,
        parsed_edge_processing=edge,
        cut_to_size=cut_to_size)
    db.session.add(produkt)
    db.session.commit()
    return produkt


# ============================================================================
# KODY STANOWISK I MAPA STATUSÓW
# ============================================================================

def test_surowy_z_krawedziami_z_formatowania_idzie_na_krawedzie(app):
    with app.app_context():
        produkt = _produkt(finish='surowe', edge=True)
        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_krawedzie'
        assert produkt.formatting_completed_at is not None


def test_lakierowany_z_krawedziami_z_formatowania_idzie_na_krawedzie(app):
    with app.app_context():
        produkt = _produkt(finish='lakierowane', edge=True)
        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_krawedzie'


def test_z_krawedzi_surowy_idzie_do_logistyki(app):
    """
    Dowód, że KLUCZ mapy następnych statusów nazywa się dziś 'edges'.
    Implementacja, która znormalizuje wejście, ale zostawi w mapie stary klucz
    'finishing', przeleci obok całego bloku tranzycji: licznik się zapisze,
    a current_status zostanie bez zmian i zlecenie utknie na stanowisku.
    """
    with app.app_context():
        produkt = _produkt(finish='surowe', edge=True, status='czeka_na_krawedzie')
        produkt.complete_task('edges')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_logistyke'
        assert produkt.edges_completed_at is not None


def test_z_krawedzi_olejowany_idzie_do_lakierni(app):
    with app.app_context():
        produkt = _produkt(finish='olejowane', edge=True, status='czeka_na_krawedzie')
        produkt.complete_task('edges')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_lakiernie'


def test_z_krawedzi_lakierowany_idzie_do_lakierni(app):
    with app.app_context():
        produkt = _produkt(finish='lakierowane', edge=True, status='czeka_na_krawedzie')
        produkt.complete_task('edges')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_lakiernie'


def test_lakiernia_konczy_na_logistyce(app):
    with app.app_context():
        produkt = _produkt(finish='olejowane', edge=True, status='czeka_na_lakiernie')
        produkt.complete_task('painting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_logistyke'
        assert produkt.painting_completed_at is not None


def test_alias_finishing_domyka_krawedzie(app):
    """
    Stary tablet przysyła 'finishing' — ma trafić w tę samą gałąź co 'edges'.

    Dowód, że WEJŚCIE jest normalizowane. Implementacja, która przemianuje
    klucz mapy na 'edges', ale nie zawoła resolve_station_code, przeleci tu
    obok bloku tranzycji i zostawi produkt na Krawędziach.
    """
    with app.app_context():
        produkt = _produkt(finish='olejowane', edge=True, status='czeka_na_krawedzie')
        produkt.complete_task('finishing')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_lakiernie'
        assert produkt.edges_completed_at is not None
        assert not hasattr(produkt, 'finishing_completed_at')


def test_alias_finishing_z_bialymi_znakami_tez_domyka_krawedzie(app):
    """
    Wzmocnienie ponad brief. Zła implementacja z zaszytym na sztywno
    `if station_code == 'finishing': station_code = 'edges'` (parafraza
    kontraktu zamiast wywołania resolve_station_code) przeszłaby test aliasu
    powyżej, ale tu przeleciałaby obok mapy — a starsze APK tabletów wysyłają
    kod z białymi znakami, które resolve_station_code przycina.
    """
    with app.app_context():
        produkt = _produkt(finish='surowe', edge=True, status='czeka_na_krawedzie')
        produkt.complete_task('  finishing  ')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_logistyke'
        assert produkt.edges_completed_at is not None
        assert not hasattr(produkt, 'finishing_completed_at')


def test_complete_task_nie_wywraca_sie_na_kodzie_nie_stringowym(app):
    """
    Wzmocnienie ponad brief. Kontrakt resolve_station_code każe zwrócić
    wartość nie-stringową bez zmian i bez wyjątku; complete_task ma wtedy
    po prostu nie znaleźć kodu w mapie i zostawić status w spokoju.
    Implementacja wołająca `station_code.strip()` wprost (parafraza kontraktu)
    wywaliłaby tu AttributeError — na produkcji 500 zamiast czytelnego 400.
    """
    with app.app_context():
        produkt = _produkt(finish='surowe', edge=True)
        produkt.complete_task(None)
        db.session.commit()
        assert produkt.current_status == 'czeka_na_formatowanie'


def test_formatowanie_z_krawedziami_nie_zalicza_z_gory_pracy_na_krawedziach(app):
    """
    Wzmocnienie ponad brief. Produkt, który NA Krawędzie idzie, nie może
    dostać licznika ani znacznika Krawędzi przy wyjściu z formatowania.
    Zła implementacja, która postawi `set_quantity_done('edges', ...)` poza
    strażnikiem should_skip_edges(), przejdzie wszystkie testy statusów —
    a na hali tablet Krawędzi pokaże sztuki jako zrobione, zanim ktokolwiek
    ich dotknie, i praca brygady nie zostanie policzona.
    """
    with app.app_context():
        produkt = _produkt(finish='olejowane', edge=True, quantity=7)
        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_krawedzie'
        assert produkt.quantity_done_edges == 0
        assert produkt.edges_completed_at is None
        assert ProductionStationEvent.query.filter_by(station_code='edges').count() == 0


def test_skrot_cut_to_size_pomija_formatowanie_i_krawedzie_i_nie_wchodzi_do_lakierni(app):
    """
    Skrót zachowuje dzisiejsze zachowanie: zamyka formatowanie i Krawędzie dla
    KAŻDEGO wykończenia, także olejowanego, i jedzie prosto do logistyki.
    Zmienia się w nim wyłącznie nazwa odhaczanego stanowiska.
    """
    with app.app_context():
        produkt = _produkt(finish='olejowane', edge=True, cut_to_size=False,
                           status='czeka_na_sklejanie')
        produkt.complete_task('gluing')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_logistyke'
        assert produkt.quantity_done_formatting == produkt.quantity
        assert produkt.quantity_done_edges == produkt.quantity
        assert produkt.edges_completed_at is not None
        assert produkt.quantity_done_painting == 0
        assert produkt.painting_completed_at is None
        assert not hasattr(produkt, 'finishing_completed_at')


def test_domkniecie_dorobki_na_formatowaniu_dziala_dalej(app):
    """Regresja obok zmienianego kodu: doróbka wracająca na formatowanie ma
    dalej gasić ręczny priorytet i zamykać wpis audytu (models.py:530-543)."""
    with app.app_context():
        oryginal = _produkt(finish='surowe', edge=True)
        dorobka = _produkt(finish='surowe', edge=True, status='czeka_na_sklejanie')
        dorobka.original_product_id = oryginal.id
        dorobka.priority_manual_override = True
        dorobka.is_priority = True
        wpis = ProductionReworkLog(
            original_product_id=oryginal.id, rework_product_id=dorobka.id,
            quantity=2, rejected_at_station='formatting',
            returned_to_station='cutting', reason_category='wymiary')
        db.session.add(wpis)
        db.session.commit()

        dorobka.complete_task('gluing')
        db.session.commit()

        assert dorobka.current_status == 'czeka_na_formatowanie'
        assert dorobka.priority_manual_override is False
        assert dorobka.is_priority is False
        assert wpis.closed_at is not None


# ============================================================================
# REGUŁA POMIJANIA KRAWĘDZI I CZTERY ŚCIEŻKI PRODUKTU
# ============================================================================

def test_should_skip_edges_zalezy_wylacznie_od_obrobki_krawedzi(app):
    """
    Nowa reguła ZRYWA związek z parsed_finish_type: bez obróbki krawędzi nie ma
    czego robić na Krawędziach, niezależnie od wykończenia.
    """
    with app.app_context():
        assert _produkt(finish='surowe', edge=True).should_skip_edges() is False
        assert _produkt(finish='surowe', edge=False).should_skip_edges() is True
        assert _produkt(finish='olejowane', edge=True).should_skip_edges() is False
        assert _produkt(finish='lakierowane', edge=False).should_skip_edges() is True
        assert not hasattr(_produkt(), 'should_skip_finishing')


def test_should_skip_edges_traktuje_brak_danych_jak_brak_krawedzi():
    """
    Wzmocnienie ponad brief. Produkt świeżo sparsowany (albo przywrócony
    z backupu sprzed NOT NULL) ma parsed_edge_processing = None. Zła
    implementacja `return self.parsed_edge_processing is False` przeszłaby
    cztery asercje powyżej, a tu odpowiedziałaby False — czyli wysłałaby na
    Krawędzie sztukę, o której nie wiadomo, czy ma tam co robić.
    """
    produkt = ProductionProduct(quantity=10, parsed_edge_processing=None)
    assert produkt.should_skip_edges() is True


def test_surowy_bez_krawedzi_z_formatowania_idzie_do_logistyki(app):
    with app.app_context():
        produkt = _produkt(finish='surowe', edge=False)
        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_logistyke'


def test_olejowany_bez_krawedzi_z_formatowania_idzie_prosto_do_lakierni(app):
    """NOWA GAŁĄŹ — ścieżka, której stary routing nie potrafił wytworzyć."""
    with app.app_context():
        produkt = _produkt(finish='olejowane', edge=False)
        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_lakiernie'


def test_lakierowany_bez_krawedzi_z_formatowania_idzie_prosto_do_lakierni(app):
    with app.app_context():
        produkt = _produkt(finish='lakierowane', edge=False)
        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_lakiernie'


def test_pominiete_krawedzie_dostaja_licznik_znacznik_i_event_systemu(app):
    """
    Parytet z dzisiejszym pomijaniem surowych: licznik na pełno, znacznik czasu
    ustawia się sam (value >= quantity, models.py:445-447), a event ma źródło
    'system' — żeby nikt nie dostał kredytu za pracę, której nie wykonał.
    """
    with app.app_context():
        produkt = _produkt(finish='olejowane', edge=False, quantity=7)
        produkt.complete_task('formatting')
        db.session.commit()

        assert produkt.quantity_done_edges == 7
        assert produkt.edges_completed_at is not None
        eventy = ProductionStationEvent.query.filter_by(station_code='edges').all()
        assert len(eventy) == 1
        assert eventy[0].source == 'system'
        assert eventy[0].quantity_done_after == 7


def test_pominiecie_krawedzi_nie_domyka_lakierni(app):
    """Strażnik: przeskok formatowanie → Lakiernia nie ma prawa wpisać
    quantity_done_painting ani znacznika lakierni."""
    with app.app_context():
        produkt = _produkt(finish='lakierowane', edge=False, quantity=7)
        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.quantity_done_painting == 0
        assert produkt.painting_completed_at is None
        assert ProductionStationEvent.query.filter_by(station_code='painting').count() == 0


def test_odbior_osobisty_zamienia_logistyke_na_pakowanie_na_kazdym_z_trzech_wyjsc(app):
    """Trzy drogi do logistyki: formatowanie (surowy bez krawędzi), Krawędzie
    (surowy) i Lakiernia. Każda musi uwzględnić odbiór osobisty (models.py:518-521)."""
    with app.app_context():
        z_formatowania = _produkt(finish='surowe', edge=False, odbior_osobisty=True)
        z_formatowania.complete_task('formatting')

        z_krawedzi = _produkt(finish='surowe', edge=True, odbior_osobisty=True,
                              status='czeka_na_krawedzie')
        z_krawedzi.complete_task('edges')

        z_lakierni = _produkt(finish='olejowane', edge=True, odbior_osobisty=True,
                              status='czeka_na_lakiernie')
        z_lakierni.complete_task('painting')
        db.session.commit()

        assert z_formatowania.current_status == 'czeka_na_pakowanie'
        assert z_krawedzi.current_status == 'czeka_na_pakowanie'
        assert z_lakierni.current_status == 'czeka_na_pakowanie'
        assert z_lakierni.order.logistics_completed_at is not None


# ============================================================================
# CZTERY ŚCIEŻKI PRODUKTU — PRZEBIEG OD FORMATOWANIA DO LOGISTYKI
# ============================================================================
#
# Wzmocnienie ponad brief. Testy powyżej sprawdzają POJEDYNCZE przejścia, każde
# na świeżo zbudowanym produkcie o ręcznie ustawionym statusie startowym. Taki
# zestaw przechodzi także dla implementacji, w której przejścia są poprawne
# osobno, ale nie SKŁADAJĄ SIĘ w trasę: np. gdy pominięcie Krawędzi zamiast
# ustawiać licznik przestawia status na 'czeka_na_krawedzie' i produkt krąży,
# albo gdy wyjście z Lakierni czyta wykończenie i zawraca sztukę na Krawędzie.
# Poniższe cztery testy prowadzą JEDEN produkt przez całą trasę, odhaczając
# kolejne stanowiska w takiej kolejności, w jakiej robią to tablety na hali.

def test_sciezka_surowy_bez_krawedzi_formatowanie_logistyka(app):
    """Ścieżka 1/4: surowy, bez krawędzi → logistyka."""
    with app.app_context():
        produkt = _produkt(finish='surowe', edge=False, quantity=5)
        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_logistyke'
        assert produkt.quantity_done_edges == 5
        assert produkt.quantity_done_painting == 0
        assert produkt.painting_completed_at is None


def test_sciezka_olejowany_bez_krawedzi_formatowanie_lakiernia_logistyka(app):
    """Ścieżka 2/4: olejowany, bez krawędzi → Lakiernia → logistyka.
    NOWA GAŁĄŹ — stary routing nie potrafił jej wytworzyć."""
    with app.app_context():
        produkt = _produkt(finish='olejowane', edge=False, quantity=5)

        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_lakiernie'

        produkt.complete_task('painting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_logistyke'
        assert produkt.painting_completed_at is not None


def test_sciezka_surowy_z_krawedziami_formatowanie_krawedzie_logistyka(app):
    """Ścieżka 3/4: surowy, z krawędziami → Krawędzie → logistyka."""
    with app.app_context():
        produkt = _produkt(finish='surowe', edge=True, quantity=5)

        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_krawedzie'
        assert produkt.edges_completed_at is None

        produkt.set_quantity_done('edges', 5, source='mobile')
        produkt.complete_task('edges')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_logistyke'
        assert produkt.edges_completed_at is not None
        assert produkt.quantity_done_painting == 0


def test_sciezka_lakierowany_z_krawedziami_formatowanie_krawedzie_lakiernia_logistyka(app):
    """Ścieżka 4/4: lakierowany, z krawędziami → Krawędzie → Lakiernia → logistyka."""
    with app.app_context():
        produkt = _produkt(finish='lakierowane', edge=True, quantity=5)

        produkt.complete_task('formatting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_krawedzie'

        produkt.set_quantity_done('edges', 5, source='mobile')
        produkt.complete_task('edges')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_lakiernie'

        produkt.set_quantity_done('painting', 5, source='mobile')
        produkt.complete_task('painting')
        db.session.commit()
        assert produkt.current_status == 'czeka_na_logistyke'
        assert produkt.painting_completed_at is not None
