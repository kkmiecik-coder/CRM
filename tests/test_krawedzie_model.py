# -*- coding: utf-8 -*-
"""
Model produkcji po podziale Wykańczania na Krawędzie i Lakiernię.

Warstwa W1: enum statusu, nazwy kolumn licznika i znacznika czasu, normalizacja
przejściowego kodu 'finishing' oraz zbiory kodów stanowisk. Routing produktu ma
własny plik — tests/test_routing_krawedzie.py.

UWAGA (zweryfikowane empirycznie na SQLAlchemy 1.4.54): Enum NIE waliduje
wartości po stronie Pythona przy ZAPISIE (validate_strings domyślnie False),
a na SQLite kolumna to zwykły VARCHAR bez CHECK. Zapis wartości spoza enuma
przechodzi bez błędu; LookupError pojawia się dopiero przy ODCZYCIE wartości
spoza enuma z bazy. Zestaw wartości sprawdzamy więc WYŁĄCZNIE na definicji
kolumny w modelu. Zielony test NIE dowodzi, że migracja MySQL powstała.

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
from modules.production.services.station_catalog import (
    STATION_ORDER, STATION_PENDING_STATUS,
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
             status='czeka_na_formatowanie'):
    """Produkt z zamówieniem KURIERSKIM.

    Adres, miasto i kod pocztowy są obowiązkowe: ProductionOrder.is_personal_pickup
    (models.py:171-183) uznaje zamówienie BEZ żadnego z tych pól za odbiór osobisty,
    co po cichu zamieniłoby logistykę na pakowanie.
    """
    numer = next(_licznik)
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
# ENUM STATUSU
# ============================================================================

def test_enum_statusu_zna_krawedzie_a_nie_wykanczanie():
    wartosci = list(ProductionProduct.__table__.c.current_status.type.enums)
    assert 'czeka_na_krawedzie' in wartosci
    assert 'czeka_na_wykanczanie' not in wartosci


def test_enum_statusu_ma_dokladnie_dwanascie_wartosci_bez_duplikatow():
    """
    Wzmocnienie testu porządku poniżej: `index(krawedzie) == index(formatowanie) + 1`
    sprawdza WYŁĄCZNIE pozycję względną, więc przepuściłby literówkę wstawiającą
    'czeka_na_krawedzie' DRUGI raz gdzieś dalej w liście (np. przez kopiuj-wklej
    całego bloku) — pierwsze wystąpienie nadal siedziałoby na właściwym miejscu,
    a `index()` zwraca zawsze PIERWSZE dopasowanie, więc duplikat by się nie ujawnił.
    Tu liczymy elementy wprost i porównujemy z zbiorem, żeby taki duplikat złapać.
    """
    wartosci = list(ProductionProduct.__table__.c.current_status.type.enums)
    assert len(wartosci) == 12
    assert len(wartosci) == len(set(wartosci))


def test_status_krawedzi_stoi_miedzy_formatowaniem_a_lakiernia():
    """Kolejność wartości to kontrakt z ostatnim ALTER-em migracji (sekcja 6)."""
    wartosci = list(ProductionProduct.__table__.c.current_status.type.enums)
    assert wartosci.index('czeka_na_krawedzie') == wartosci.index('czeka_na_formatowanie') + 1
    assert wartosci.index('czeka_na_lakiernie') == wartosci.index('czeka_na_krawedzie') + 1


def test_kazdy_status_kolejki_z_katalogu_jest_w_enumie_produktu():
    """
    Sprzęgło katalog ↔ model. station_catalog (W0) już mówi 'czeka_na_krawedzie';
    dopóki enum modelu o tym nie wie, dashboard i raporty filtrują po wartości,
    której nie da się zapisać. Rozjazd MUSI być czerwony, a nie cichy.
    """
    wartosci = set(ProductionProduct.__table__.c.current_status.type.enums)
    for kod in STATION_ORDER:
        assert STATION_PENDING_STATUS[kod] in wartosci, kod


def test_nazwa_statusu_krawedzi_jest_po_polsku():
    produkt = ProductionProduct(current_status='czeka_na_krawedzie')
    assert produkt.status_display_name == 'Czeka na krawędzie'


def test_archiwalny_status_wykanczania_dalej_ma_nazwe():
    """
    prod_product_events trzyma 'czeka_na_wykanczanie' jako ZWYKŁY TEKST
    w old_value/new_value (423 wiersze na produkcji). Historia produktu nie może
    po zmianie pokazywać surowego kodu, więc etykieta zostaje mimo zdjęcia
    wartości z enuma.
    """
    produkt = ProductionProduct(current_status='czeka_na_wykanczanie')
    assert produkt.status_display_name == 'Czeka na wykańczanie (archiwalne)'


# ============================================================================
# KOLUMNY I NORMALIZACJA ALIASU
# ============================================================================

def test_produkt_ma_kolumny_krawedzi_a_nie_wykanczania():
    kolumny = set(ProductionProduct.__table__.columns.keys())
    assert 'quantity_done_edges' in kolumny
    assert 'edges_completed_at' in kolumny
    assert 'quantity_done_finishing' not in kolumny
    assert 'finishing_completed_at' not in kolumny
    # Kolizja nazw, o którą łatwo się potknąć: parsed_edges_groups to DANE
    # PRODUKTU (opis krawędzi), a nie licznik stanowiska. Obie zostają.
    assert 'parsed_edges_groups' in kolumny


def test_kazde_stanowisko_z_katalogu_ma_kolumny_w_modelu():
    """
    Drugie sprzęgło katalog ↔ model (pierwsze jest przy enumie statusu).
    Uogólnienie testu z test_display_monitor_service.py:29 na CAŁY katalog:
    kod bez pary kolumn daje CICHE zero w monitorze i w raporcie, bo wszyscy
    czytają te pola przez getattr z defaultem.
    """
    for kod in STATION_ORDER:
        assert hasattr(ProductionProduct, 'quantity_done_%s' % kod), kod
        assert hasattr(ProductionProduct, '%s_completed_at' % kod), kod


def test_import_katalogu_w_modelu_nie_rozwala_serwisow():
    """
    modules/production/__init__.py:37-49 i services/__init__.py importują
    serwisy w try/except ImportError. Cykl importów wywołany nowym importem
    w models.py NIE rzuciłby wyjątku widocznego dla użytkownika — po cichu
    ustawiłby BaselinkerSyncService na None.
    """
    from modules.production.services import (
        BaselinkerSyncService, ProductionConfigService, IPSecurityService,
        ProductNameParser, NewPriorityCalculator,
    )
    assert BaselinkerSyncService is not None
    assert ProductionConfigService is not None
    assert IPSecurityService is not None
    assert ProductNameParser is not None
    assert NewPriorityCalculator is not None


def test_alias_finishing_czyta_licznik_krawedzi():
    """Bez normalizacji getattr z defaultem zwróciłby CICHO 0."""
    produkt = ProductionProduct(quantity=10)
    produkt.quantity_done_edges = 4
    assert produkt.get_quantity_done('finishing') == 4
    assert produkt.get_quantity_done('edges') == 4
    # Wzmocnienie: zła implementacja z zaszytym na sztywno
    # `if station_code == 'finishing'` (zamiast wołania resolve_station_code)
    # przepuściłaby powyższe dwie asercje, ale po cichu zwróciłaby 0 dla kodu
    # z białymi znakami — dokładnie taki, jaki wysyłają starsze APK tabletów
    # (resolve_station_code go przycina).
    assert produkt.get_quantity_done('  finishing  ') == 4
    # None nie jest stringiem — kontrakt resolve_station_code każe zwrócić go
    # bez zmian i bez wyjątku. Zła implementacja wołająca `.strip()` wprost na
    # station_code (parafraza kontraktu) wywaliłaby tu AttributeError zamiast
    # spokojnie oddać wartość domyślną z getattr.
    assert produkt.get_quantity_done(None) == 0


def test_alias_finishing_zapisuje_licznik_krawedzi():
    """
    Bez normalizacji setattr tworzy atrybut-widmo (cicho), a odczyt
    quantity_done_edges leci AttributeError.
    """
    produkt = ProductionProduct(quantity=10)
    produkt.set_quantity_done('finishing', 10)
    assert produkt.quantity_done_edges == 10
    assert produkt.edges_completed_at is not None
    assert not hasattr(produkt, 'quantity_done_finishing')
    # Wzmocnienie: kod z białymi znakami musi też trafić do quantity_done_edges,
    # nie do atrybutu-widma — łapie implementację z zaszytym na sztywno
    # porównaniem stringów zamiast delegacji do resolve_station_code.
    produkt2 = ProductionProduct(quantity=10)
    produkt2.set_quantity_done('  finishing  ', 6)
    assert produkt2.quantity_done_edges == 6


def test_alias_nie_zostawia_eventu_z_martwym_kodem(app):
    """prod_station_events.station_code to String(32) bez enuma i bez FK —
    literówka zapisałaby się bez błędu i wypadła ze wszystkich raportów."""
    with app.app_context():
        produkt = _produkt(quantity=10)
        produkt.set_quantity_done('finishing', 3, source='mobile')
        db.session.commit()
        kody = [e.station_code for e in ProductionStationEvent.query.all()]
        assert kody == ['edges']


def test_czesciowa_ilosc_kasuje_znacznik_domkniecia():
    """
    Dowód, że spóźniony PATCH /quantity z kolejki offline cofa stanowisko do
    „nieukończone" (models.py:445-449, gałąź else przy value < quantity).
    Zachowanie świadome, nie regresja — test jest tu, żeby zmiana nazw kolumn
    go nie zgubiła.
    """
    produkt = ProductionProduct(quantity=10)
    produkt.set_quantity_done('edges', 10)
    assert produkt.edges_completed_at is not None
    produkt.set_quantity_done('edges', 4)
    assert produkt.edges_completed_at is None


# ============================================================================
# KODY STANOWISK URZĄDZEŃ
# ============================================================================

def test_tablet_moze_sie_zarejestrowac_na_krawedziach_i_w_lakierni():
    """
    Bez 'painting' walidator odrzuca rejestrację tabletu Lakierni ORAZ blokuje
    przypisanie pracownika (worker_service._normalize_stations waliduje tym
    samym zbiorem — dziś station_choices() oferuje Lakiernię, a zapis leci 422).
    """
    assert 'edges' in ProductionDevice.VALID_STATION_CODES
    assert 'painting' in ProductionDevice.VALID_STATION_CODES


def test_stary_kod_finishing_zostaje_na_okres_przejsciowy():
    """Stare APK rejestruje się jeszcze jako 'finishing'; bez tego wpisu
    nie odnowi JWT i dostanie 400 invalid_station_code."""
    assert 'finishing' in ProductionDevice.VALID_STATION_CODES


def test_walidator_przyjmuje_oba_nowe_kody_i_alias(app):
    with app.app_context():
        for kod in ('edges', 'painting', 'finishing'):
            db.session.add(ProductionDevice(device_id='tablet-%s' % kod,
                                            station_code=kod))
        db.session.commit()
        assert ProductionDevice.query.count() == 3


def test_walidator_dalej_odrzuca_kod_spoza_zbioru():
    with pytest.raises(ValueError):
        ProductionDevice(device_id='tablet-x', station_code='krawedzie')


def test_zbior_kodow_urzadzen_ma_dokladnie_dziewiec_wpisow():
    """
    Wzmocnienie ponad brief: same asercje 'in' przeszłyby też na zbiorze-worku,
    do którego ktoś przez pomyłkę dorzucił dodatkowe/martwe kody (np. zostawił
    stary 'wykanczanie' obok nowego 'edges', albo dopisał coś z domeny
    produktu). Zamykamy zbiór na dokładnej liczebności i treści, żeby zła
    implementacja „dodaj i nic nie usuwaj na wszelki wypadek" też oblała.
    """
    assert ProductionDevice.VALID_STATION_CODES == {
        'packaging', 'cutting', 'assembly', 'gluing', 'formatting',
        'edges', 'painting', 'finishing', 'sawmill',
    }


# ============================================================================
# ENUM STANOWISKA DORÓBKI
# ============================================================================

def test_enum_stanowiska_dorobki_zna_krawedzie():
    """
    Po wpięciu aliasu w routerze mobilnym do rejected_at_station trafi 'edges'
    (mobile_api.py, jedyny writer tej kolumny). Wartość musi być w enumie,
    inaczej MySQL odrzuci zapis błędem 1265 — SQLite tego nie złapie, patrz
    docstring pliku.

    Porównanie całą listą, a nie `'edges' in wartosci`: zbiór domyka się na
    dokładnej treści i kolejności, więc implementacja „dodaj edges i zostaw
    finishing na wszelki wypadek" też oblewa. Kolejność jest kontraktem
    z ALTER-em migracji.
    """
    wartosci = list(ProductionReworkLog.__table__.c.rejected_at_station.type.enums)
    assert wartosci == ['formatting', 'edges', 'painting', 'gluing', 'packaging']


def test_zapis_dorobki_z_krawedzi_przechodzi(app):
    """
    Pełna pętla zapis → odczyt dla kodu 'edges'.

    SPROSTOWANIE wobec briefu, ktory zapowiadal ten test jako zielony juz przed
    implementacja: sam ZAPIS faktycznie przechodzi (Enum nie waliduje stringow
    po stronie Pythona, SQLite nie zaklada CHECK-a), ale ODCZYT leci
    LookupError z Enum._object_value_for_elem, gdy wartosci nie ma w enumie.
    Test jest wiec czerwony przed krokiem implementacji — i mocniejszy, niz
    zakladal brief: lapie nie tylko ksztalt enuma, ale i to, ze wiersz da sie
    odczytac z powrotem.
    """
    with app.app_context():
        oryginal = _produkt(finish='surowe', edge=True)
        dorobka = _produkt(finish='surowe', edge=True, status='czeka_na_wyciecie')
        wpis = ProductionReworkLog(
            original_product_id=oryginal.id, rework_product_id=dorobka.id,
            quantity=2, rejected_at_station='edges',
            returned_to_station='cutting', reason_category='wymiary')
        db.session.add(wpis)
        db.session.commit()
        assert ProductionReworkLog.query.one().rejected_at_station == 'edges'
