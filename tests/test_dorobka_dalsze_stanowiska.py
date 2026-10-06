# -*- coding: utf-8 -*-
"""
Cofanie do doróbki z dalszych stanowisk (2026-09-23).

Do tej zmiany sztukę cofało wyłącznie formatowanie. Teraz cofają też
sklejanie, krawędzie, lakiernia i pakowanie. Cięcie i składanie zostają
poza zbiorem — to początek trasy, na który doróbka i tak wraca.

Trzy rzeczy stały się zależne od stanowiska: dozwolony status sztuki,
limit sztuk (quantity − quantity_done_<stanowisko>) i kod błędu przy złym
statusie. Formatowanie zachowuje stary kod 'product_not_in_formatting',
bo parsują go APK sprzed rozszerzenia.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfiguration, ProductionOrder, ProductionProduct,
    ProductionReworkLog, ProductionStationEvent,
)
from modules.production.services.rework_service import (
    RejectError, VALID_REASONS, reject_product_quantity,
)
from modules.users.models import User
# Importy wymagane, żeby topologiczne sortowanie FK w create_all znalazło tabelę
# 'users' — ten sam powód co w tests/test_dorobka_trasa_krawedzi.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionReworkLog, ProductionStationEvent,
)]

ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

STATUS_STANOWISKA = {
    'gluing': 'czeka_na_sklejanie',
    'edges': 'czeka_na_krawedzie',
    'painting': 'czeka_na_lakiernie',
    'packaging': 'czeka_na_pakowanie',
}


@pytest.fixture()
def app():
    aplikacja = Flask(__name__)
    aplikacja.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    aplikacja.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    aplikacja.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(aplikacja)
    with aplikacja.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield aplikacja
        db.session.remove()


def _produkt(app, **nadpisania):
    with app.app_context():
        order = ProductionOrder(
            baselinker_order_id=990077,
            internal_order_number='26/00077',
            delivery_method='Kurier DPD',
            delivery_address='ul. Bukowa 7',
            delivery_city='Poznań',
            delivery_postcode='61-001',
        )
        db.session.add(order)
        db.session.flush()

        dane = dict(
            order_id=order.id,
            short_product_id='26077_1',
            product_sequence_in_order=1,
            original_product_name='Blat dębowy 200x60x4',
            quantity=3,
            current_status='czeka_na_formatowanie',
            parsed_finish_type='lakierowane',
            parsed_edge_processing=True,
            cut_to_size=True,
            cutting_completed_at=None,
        )
        dane.update(nadpisania)
        product = ProductionProduct(**dane)
        db.session.add(product)
        db.session.commit()
        return product.id


@pytest.mark.parametrize('stanowisko', sorted(STATUS_STANOWISKA))
def test_dalsze_stanowisko_cofa_sztuke_na_poczatek_trasy(app, stanowisko):
    product_id = _produkt(app, current_status=STATUS_STANOWISKA[stanowisko])

    with app.app_context():
        oryginal, dorobka, wpis = reject_product_quantity(
            product_id=product_id,
            quantity=1,
            reason_category='jakosc_produktu',
            rejected_at_station=stanowisko,
        )

        assert oryginal.quantity == 2
        assert oryginal.current_status == STATUS_STANOWISKA[stanowisko]
        assert dorobka.quantity == 1
        assert dorobka.current_status == 'czeka_na_wyciecie'
        assert wpis.rejected_at_station == stanowisko
        assert wpis.returned_to_station == 'cutting'


@pytest.mark.parametrize('stanowisko', sorted(STATUS_STANOWISKA))
def test_sztuka_z_innego_stanowiska_dostaje_nowy_kod(app, stanowisko):
    """Tablet cofa tylko to, co czeka NA NIM — nie sztukę z sąsiedniej kolejki."""
    product_id = _produkt(app, current_status='czeka_na_formatowanie')

    with app.app_context():
        with pytest.raises(RejectError) as wyjatek:
            reject_product_quantity(
                product_id=product_id, quantity=1,
                reason_category='inne', rejected_at_station=stanowisko,
            )
        assert wyjatek.value.code == 'product_not_on_station'
        assert wyjatek.value.status == 409


def test_w_realizacji_przechodzi_tylko_na_formatowaniu(app):
    """
    'w_realizacji' to stary status z czasów, gdy cofało samo formatowanie.
    Dalsze stanowiska nigdy go nie miały, więc nie dostają furtki.
    """
    product_id = _produkt(app, current_status='w_realizacji')

    with app.app_context():
        with pytest.raises(RejectError) as wyjatek:
            reject_product_quantity(
                product_id=product_id, quantity=1,
                reason_category='inne', rejected_at_station='edges',
            )
        assert wyjatek.value.code == 'product_not_on_station'

        _org, dorobka, _wpis = reject_product_quantity(
            product_id=product_id, quantity=1,
            reason_category='inne', rejected_at_station='formatting',
        )
        assert dorobka.quantity == 1


def test_formatowanie_zachowuje_stary_kod_bledu(app):
    """Stare APK parsują 'product_not_in_formatting' — nie wolno go zmienić."""
    product_id = _produkt(app, current_status='czeka_na_lakiernie')

    with app.app_context():
        with pytest.raises(RejectError) as wyjatek:
            reject_product_quantity(
                product_id=product_id, quantity=1,
                reason_category='wymiary', rejected_at_station='formatting',
            )
        assert wyjatek.value.code == 'product_not_in_formatting'
        assert wyjatek.value.status == 409


def test_limit_liczy_sztuki_zrobione_na_cofajacym_stanowisku(app):
    """
    Sztuki oznaczone jako zrobione na danym stanowisku fizycznie poszły dalej.
    Limit z formatowania (quantity_done_formatting = quantity, bo sztuka
    je przeszła) zablokowałby każde cofnięcie z lakierni.
    """
    product_id = _produkt(
        app, current_status='czeka_na_lakiernie', quantity=3,
        quantity_done_formatting=3, quantity_done_painting=2,
    )

    with app.app_context():
        with pytest.raises(RejectError) as wyjatek:
            reject_product_quantity(
                product_id=product_id, quantity=2,
                reason_category='jakosc_lakierowania', rejected_at_station='painting',
            )
        assert wyjatek.value.code == 'invalid_quantity'
        db.session.rollback()

        oryginal, _dorobka, _wpis = reject_product_quantity(
            product_id=product_id, quantity=1,
            reason_category='jakosc_lakierowania', rejected_at_station='painting',
        )
        assert oryginal.quantity == 2
        # Licznik stanowiska cofającego zostaje — liczy sztuki, które poszły dalej.
        assert oryginal.quantity_done_painting == 2


def test_cofniecie_z_pakowania_przycina_stan_druku_etykiet(app):
    """
    label_printed_units trzyma numery LOKALNE 1..quantity. Po zmniejszeniu
    ilości numer 3 wskazywałby sztukę, której pozycja już nie ma — ta należy
    teraz do doróbki, która startuje z pustym stanem druku.
    """
    product_id = _produkt(
        app, current_status='czeka_na_pakowanie', quantity=3,
        label_printed_units=[1, 2, 3], label_print_count=3,
    )

    with app.app_context():
        oryginal, dorobka, _wpis = reject_product_quantity(
            product_id=product_id, quantity=1,
            reason_category='jakosc_produktu', rejected_at_station='packaging',
        )

        assert oryginal.label_printed_units == [1, 2]
        assert oryginal.label_print_count == 2
        assert not dorobka.label_printed_units
        assert not dorobka.label_print_count


@pytest.mark.parametrize('przyczyna', ['jakosc_krawedzi', 'jakosc_lakierowania'])
def test_nowe_przyczyny_sa_przyjmowane(app, przyczyna):
    product_id = _produkt(app, current_status='czeka_na_krawedzie')

    with app.app_context():
        _org, _dor, wpis = reject_product_quantity(
            product_id=product_id, quantity=1,
            reason_category=przyczyna, rejected_at_station='edges',
        )
        assert wpis.reason_category == przyczyna


def test_przyczyny_serwisu_zgadzaja_sie_z_enumem_i_raportem():
    from modules.production.services.reports_service import ETYKIETY_POWODOW_DOROBEK

    enum = set(ProductionReworkLog.reason_category.type.enums)
    assert VALID_REASONS == enum
    assert set(ETYKIETY_POWODOW_DOROBEK) == enum


def test_migracja_rozszerza_oba_enumy_zgodnie_z_modelem():
    """SQLite nie odtworzy błędu 1265 — zgodność migracji z modelem pilnujemy tekstem."""
    tresc = (Path(__file__).resolve().parents[1] / 'migrations'
             / '2026-09-23-dorobka-z-dalszych-stanowisk.sql').read_text(encoding='utf-8')
    bez_bialych = ''.join(tresc.split())

    for kolumna in ('rejected_at_station', 'reason_category'):
        wartosci = getattr(ProductionReworkLog, kolumna).type.enums
        enum_sql = 'ENUM({})'.format(','.join("'{}'".format(w) for w in wartosci))
        assert 'MODIFYCOLUMN{}{}NOTNULL'.format(kolumna, enum_sql) in bez_bialych, kolumna
