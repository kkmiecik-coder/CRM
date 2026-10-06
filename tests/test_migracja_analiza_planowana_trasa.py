# -*- coding: utf-8 -*-
"""Jednorazowa migracja nazwy statusu 417343 w historycznych wierszach Analizy sprzedażowej
(logistyka etap 4, krok 4.4b; spec 14).

Zanim mapa `STATUSY_BASELINKER` poznała status 417343, ingest zapisywał go jako „Status 417343”.
Od commita 73232c57 mapa daje „Planowana trasa”, ale wiersze z przeszłości zostają ze starą nazwą,
więc ten sam status siedział w dwóch kubełkach. Migracja poprawia je RAZ.

Testy jadą na SQLite, która nie zna MySQL-a — sprawdzamy kształt pliku i zachowanie polecenia
UPDATE przez TEN SAM kod, którego używa runner (`MigrationService.execute_sql_migration`). Przebieg
na prawdziwym MySQL 8.4 (dwa razy, liczba wierszy) potwierdza się osobno, na kontenerze `db`.
"""
import os
import re
from datetime import date, datetime
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from migrations.migration_service import MigrationService
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.reports.service import STATUSY_BASELINKER

# Rejestr mapperów: bez tych modeli konfiguracja SQLAlchemy nie znajduje klas z relacji (np. User -> Multiplier).
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
from modules.production.models import ProductionOrder  # noqa: F401
from modules.users.models import User  # noqa: F401
import modules.quotes.models  # noqa: F401

KATALOG_MIGRACJI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')
MIGRACJA = os.path.join(KATALOG_MIGRACJI, '2026-10-01-analiza-planowana-trasa.sql')
STARA_NAZWA = 'Status 417343'
NOWA_NAZWA = 'Planowana trasa'
ID_STATUSU = 417343
ID_ZALADOWANE = 524520
ZNACZNIK_ZAPISU = datetime(2026, 9, 25, 8, 0, 0)


def _tresc():
    with open(MIGRACJA, encoding='utf-8') as f:
        return f.read()


def _polecenia():
    return [' '.join(p.split()) for p in MigrationService.split_statements(_tresc())]


# --- kształt pliku ---------------------------------------------------------

def test_plik_istnieje():
    assert os.path.exists(MIGRACJA), 'brak pliku migracji'


def test_runner_rozpoznaje_nazwe_pliku():
    """STRAŻNIK: nazwa spoza wzorca runnera = migracja POMINIĘTA po cichu."""
    assert MigrationService(db=None)._match(os.path.basename(MIGRACJA)) is not None


def test_sortuje_sie_po_migracji_zakladajacej_tabele_sprzedazy():
    """Runner jedzie w kolejności sorted() po nazwie pliku, a `sales_orders` musi już istnieć. Jedyna zależność
    tej migracji; od migracji logistyki (`2026-10-01-logistyka-dostawa.sql`) jest niezależna, więc kolejność
    względem niej nie ma znaczenia."""
    assert os.path.basename(MIGRACJA) > '2026-09-22-sales-tabele.sql'


def test_nie_uzywa_zmiany_separatora_polecen():
    assert 'DELIMITER' not in _tresc().upper()


def test_jedno_polecenie_update_z_wlasciwym_warunkiem():
    polecenia = _polecenia()
    assert polecenia == [
        "UPDATE sales_orders SET current_status = 'Planowana trasa' "
        "WHERE baselinker_status_id = 417343 AND current_status = 'Status 417343'"
    ], polecenia


def test_nazwa_w_migracji_jest_taka_sama_jak_w_mapie_statusow():
    """Bajt w bajt: inaczej wiersze po migracji i nowe wiersze z ingestu trafiłyby do dwóch kubełków."""
    assert STATUSY_BASELINKER[ID_STATUSU] == NOWA_NAZWA
    assert re.search(r"SET current_status = '([^']*)'", _polecenia()[0]).group(1) == STATUSY_BASELINKER[ID_STATUSU]
    # Stara nazwa to dokładnie to, co ingest zapisywał dla identyfikatora spoza mapy.
    assert re.search(r"current_status = '([^']*)'$", _polecenia()[0]).group(1) == f'Status {ID_STATUSU}'


# --- zachowanie na SQLite --------------------------------------------------

@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[
            SalesClient.__table__, SalesOrder.__table__, SalesOrderItem.__table__])
        yield app
        db.session.remove()


def _zamowienie(bl_id, status, status_id):
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=date(2026, 9, 20),
                     current_status=status, baselinker_status_id=status_id,
                     created_at=ZNACZNIK_ZAPISU, updated_at=ZNACZNIK_ZAPISU)
    db.session.add(zam)
    return zam


def _stan():
    """(nazwa, id statusu, updated_at) per numer zamówienia Base.; bez cache'u sesji."""
    db.session.expire_all()
    return {z.baselinker_order_id: (z.current_status, z.baselinker_status_id, z.updated_at)
            for z in SalesOrder.query.all()}


def _uruchom_jak_runner():
    MigrationService(db).execute_sql_migration({'path': Path(MIGRACJA)})


def test_zmienia_tylko_wiersze_ze_stara_nazwa_i_tym_identyfikatorem(app):
    _zamowienie(1, STARA_NAZWA, ID_STATUSU)             # to jedyne, które ma się zmienić
    _zamowienie(2, STARA_NAZWA, ID_ZALADOWANE)          # stara nazwa, inny identyfikator
    _zamowienie(3, 'Reklamacja', ID_STATUSU)            # ten identyfikator, ale inna nazwa
    _zamowienie(4, STARA_NAZWA, None)                   # brak identyfikatora
    _zamowienie(5, NOWA_NAZWA, ID_STATUSU)              # już poprawiony (świeży ingest)
    _zamowienie(6, 'Odebrane', 149779)                  # zupełnie inny status
    _zamowienie(7, None, ID_STATUSU)                    # bez nazwy
    db.session.commit()
    przed = _stan()

    _uruchom_jak_runner()

    po = _stan()
    assert po[1][:2] == (NOWA_NAZWA, ID_STATUSU)
    # Pozostałe wiersze nietknięte, co do pola.
    for numer in (2, 3, 4, 5, 6, 7):
        assert po[numer] == przed[numer], numer
    assert sum(1 for s in po.values() if s[0] == STARA_NAZWA) == 2    # wiersze 2 i 4
    assert len(po) == 7


def test_nie_rusza_updated_at(app):
    """Surowe UPDATE nie odpala `onupdate` modelu, a kolumna w MySQL nie ma ON UPDATE CURRENT_TIMESTAMP —
    znacznik czasu zostaje z chwili ostatniego zapisu ingestu (nic go nie czyta, ale też nic go nie psuje)."""
    _zamowienie(1, STARA_NAZWA, ID_STATUSU)
    db.session.commit()

    _uruchom_jak_runner()

    assert _stan()[1][2] == ZNACZNIK_ZAPISU


def test_drugie_uruchomienie_nic_nie_zmienia(app):
    _zamowienie(1, STARA_NAZWA, ID_STATUSU)
    _zamowienie(2, STARA_NAZWA, ID_STATUSU)
    _zamowienie(3, 'Odebrane', 149779)
    db.session.commit()

    _uruchom_jak_runner()
    po_pierwszym = _stan()
    wynik = db.session.execute(db.text(
        "SELECT COUNT(*) FROM sales_orders WHERE current_status = 'Status 417343' AND baselinker_status_id = 417343"
    )).scalar()
    assert wynik == 0

    _uruchom_jak_runner()

    assert _stan() == po_pierwszym
    assert po_pierwszym[1][0] == NOWA_NAZWA and po_pierwszym[2][0] == NOWA_NAZWA


def test_pusta_tabela_nie_przeszkadza(app):
    _uruchom_jak_runner()
    assert SalesOrder.query.count() == 0
