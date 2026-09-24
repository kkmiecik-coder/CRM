# -*- coding: utf-8 -*-
"""Trzy tabele Analizy sprzedazowej: klient -> zamowienie -> pozycja.

Konwencja jak tests/test_bot_api_by_token_integration.py: minimalny Flask
+ SQLAlchemy na SQLite in-memory, StaticPool (wspolne polaczenie), tworzymy
TYLKO wybrane tabele — db.create_all() probowalby skompilowac LONGTEXT
z innych modulow, czego SQLite nie potrafi.
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
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

# Import modules.reports.models_sales wykonuje modules/reports/__init__.py -> routers.py
# -> modules.users.decorators, a to jako podpakiet modules.users odpala modules/users/__init__.py,
# ktory importuje User. User ma relacje db.relationship('Multiplier') (string) — a to z kolei
# (Multiplier -> Quote -> Client, ...) ciagnie caly graf modeli kalkulatora/klientow. Ten sam
# gotcha i to samo rozwiazanie co w tests/test_bot_api_by_token_integration.py (por. jego
# docstring): trzeba zaimportowac caly zestaw, zeby SQLAlchemy mogla skonfigurowac mappery
# przy pierwszej instancjacji jakiegokolwiek modelu w procesie testowym.
from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

_TABLES = [m.__table__ for m in (SalesClient, SalesOrder, SalesOrderItem)]


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


def test_zamowienie_ma_klienta_i_pozycje(app):
    with app.app_context():
        klient = SalesClient(email_norm='jan@example.com', display_name='Jan Makietowy')
        db.session.add(klient)
        db.session.flush()

        zam = SalesOrder(baselinker_order_id=50854536, client_id=klient.id,
                         date_created=date(2026, 10, 1), caretaker='Łukasz Próbny')
        db.session.add(zam)
        db.session.flush()

        db.session.add(SalesOrderItem(
            order_id=zam.id, wood_species='dąb', technology='lity', wood_class='A/B',
            quantity=2, value_net=Decimal('862.40'), total_volume=Decimal('0.0448')))
        db.session.commit()

        wczytane = SalesOrder.query.first()
        assert wczytane.client.display_name == 'Jan Makietowy'
        assert len(wczytane.items) == 1
        assert wczytane.items[0].wood_species == 'dąb'


def test_baselinker_order_id_jest_unikalny(app):
    """Jedno zamowienie BL = jeden wiersz. To wlasnie ta unikalnosc sprawia,
    ze saldo przestaje sie powielac na pozycjach."""
    from sqlalchemy.exc import IntegrityError
    with app.app_context():
        db.session.add(SalesOrder(baselinker_order_id=111, date_created=date(2026, 10, 1)))
        db.session.commit()
        db.session.add(SalesOrder(baselinker_order_id=111, date_created=date(2026, 10, 2)))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_usuniecie_zamowienia_kasuje_pozycje(app):
    with app.app_context():
        zam = SalesOrder(baselinker_order_id=222, date_created=date(2026, 10, 1))
        db.session.add(zam)
        db.session.flush()
        db.session.add(SalesOrderItem(order_id=zam.id, quantity=1))
        db.session.commit()

        db.session.delete(zam)
        db.session.commit()
        assert SalesOrderItem.query.count() == 0


def test_klient_bez_kluczy_jest_oznaczony_do_scalenia(app):
    with app.app_context():
        k = SalesClient(display_name='Nieznany klient', needs_merge=True)
        db.session.add(k)
        db.session.commit()
        assert SalesClient.query.filter_by(needs_merge=True).count() == 1


# ===== tozsamosc pozycji: UNIQUE(order_id, bl_order_product_id) ==========
#
# ZNALEZISKO WAZNE (trzecia kontrola adwersaryjna). Migracja
# `migrations/2026-09-23-unikalnosc-klucza-pozycji.sql` zalozyla to
# ograniczenie w BAZIE, ale model go nie mial. Pakiet testow buduje SQLite
# Z MODELU (`db.metadata.create_all`), wiec ograniczenia nie sprawdzal ZADEN
# test: dublet przechodzil na SQLite i padal dopiero na produkcji. To ta sama
# klasa rozjazdu model-baza, ktora w tym projekcie ugryzla juz raz (pamiec
# „Migracje maskowane przez create_all").
#
# Nazwa `uq_soi_order_bl_product` MUSI byc ta sama, co w migracji — inaczej
# `ALTER` z migracji i `CREATE TABLE` z modelu daja dwa rozne indeksy.


def test_dublet_klucza_pozycji_w_jednym_zamowieniu_jest_odrzucany(app):
    """Dwa wiersze jednego zamowienia nie moga nosic tego samego klucza BL.

    Na tym stoi cale dopasowywanie pozycji w `_upsert_pozycje`: klucz ma
    identyfikowac DOKLADNIE jeden wiersz.
    """
    from sqlalchemy.exc import IntegrityError
    with app.app_context():
        zam = SalesOrder(baselinker_order_id=333, date_created=date(2026, 10, 1))
        db.session.add(zam)
        db.session.flush()

        db.session.add(SalesOrderItem(order_id=zam.id, bl_order_product_id=991))
        db.session.commit()

        db.session.add(SalesOrderItem(order_id=zam.id, bl_order_product_id=991))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_ten_sam_klucz_w_dwoch_zamowieniach_jest_dozwolony(app):
    """Kontrola negatywna: ograniczenie jest ZLOZONE, nie na samej kolumnie.

    `order_product_id` jest unikalny w obrebie zamowienia, a nie globalnie —
    ograniczenie na samej kolumnie odrzucaloby poprawne dane.
    """
    with app.app_context():
        for numer in (444, 555):
            zam = SalesOrder(baselinker_order_id=numer, date_created=date(2026, 10, 1))
            db.session.add(zam)
            db.session.flush()
            db.session.add(SalesOrderItem(order_id=zam.id, bl_order_product_id=991))
        db.session.commit()
        assert SalesOrderItem.query.filter_by(bl_order_product_id=991).count() == 2


def test_wiersze_bez_klucza_nie_koliduja_ze_soba(app):
    """NULL nie jest rowny NULL-owi — i na tym stoi caly backfill.

    Wszystkie 7938 wierszy `sales_order_items` w woodpower_crm_local mialy
    `bl_order_product_id IS NULL` (pomiar 21.09.2026), wiec gdyby ograniczenie
    traktowalo NULL-e jak rowne, migracja nie mialaby prawa przejsc.
    Ten test przybija te semantyke, zeby nikt jej nie zalozyl na odwrot —
    i jest jednoczesnie uzasadnieniem dla normalizacji zera do NULL-a
    w `_upsert_pozycje`: ZERO juz jest rowne ZERU.
    """
    with app.app_context():
        zam = SalesOrder(baselinker_order_id=666, date_created=date(2026, 10, 1))
        db.session.add(zam)
        db.session.flush()
        db.session.add(SalesOrderItem(order_id=zam.id, bl_order_product_id=None))
        db.session.add(SalesOrderItem(order_id=zam.id, bl_order_product_id=None))
        db.session.commit()
        assert SalesOrderItem.query.count() == 2


def test_dwa_zera_w_jednym_zamowieniu_juz_koliduja(app):
    """UZASADNIENIE NORMALIZACJI 0 -> NULL w `_upsert_pozycje`.

    Dla `_identyfikator` zero i NULL znacza to samo: BRAK klucza. Dla
    ograniczenia UNIQUE znacza cos zupelnie innego - NULL-e nie koliduja
    ze soba nigdy (test wyzej), a ZERA koliduja zawsze. Wiersz, ktory ma
    w bazie doslowne 0, wywraca wiec zapis calego zamowienia bledem 1062,
    gdy tylko obok stanie drugi taki sam.

    Tego rozjazdu nie da sie zamknac czytaniem - tylko zapisem.
    """
    from sqlalchemy.exc import IntegrityError
    with app.app_context():
        zam = SalesOrder(baselinker_order_id=777, date_created=date(2026, 10, 1))
        db.session.add(zam)
        db.session.flush()
        db.session.add(SalesOrderItem(order_id=zam.id, bl_order_product_id=0))
        db.session.add(SalesOrderItem(order_id=zam.id, bl_order_product_id=0))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
