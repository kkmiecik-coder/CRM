# -*- coding: utf-8 -*-
"""
Sygnał `station:<kod>` po imporcie nowych zamówień z Base. (priorytety produkcji, K3-poprawka-1; spec 2026-10-04,
sekcja 5.4): nowe pozycje zaczynają na Wycinaniu (mikrowczep) albo Składaniu (lity), więc tablety obu stanowisk
startowych dostają sygnał — po commitach importu, nigdy w transakcji. Bez nowych pozycji sygnału nie ma.

Aplikacja i atrapy importu z tests/test_sales_ingest_wyzwalacze.py (ten plik zostaje bez zmian — konwencja K1).
"""
import pytest
from sqlalchemy import event

from extensions import db
from modules.production.models import ProductionProduct
from modules.production.services import realtime_service
from tests.test_sales_ingest_wyzwalacze import app, serwis_synchronizacji, zamowienie  # noqa: F401


@pytest.fixture()
def zdarzenia(app, monkeypatch):
    """'COMMIT' przy każdym commicie połączenia i kod stanowiska przy każdym sygnale — w kolejności."""
    lista = []
    monkeypatch.setattr(realtime_service, 'publish_station_signal', lambda kod: lista.append(kod) or True)

    def po_commicie(_polaczenie):
        lista.append('COMMIT')

    with app.app_context():
        event.listen(db.engine, 'commit', po_commicie)
        yield lista
        event.remove(db.engine, 'commit', po_commicie)


def test_import_nowych_zamowien_sygnal_na_stanowiska_startowe(app, serwis_synchronizacji, zdarzenia):
    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie()], sync_type='manual', auto_status_change=False)

        assert wynik['products_created'] == 1
        assert ProductionProduct.query.count() == 1
        assert [z for z in zdarzenia if z != 'COMMIT'] == ['cutting', 'assembly']
        # po commicie pozycji zamówienia, nie w jego transakcji
        assert 'COMMIT' in zdarzenia[:zdarzenia.index('cutting')]


def test_import_bez_nowych_pozycji_bez_sygnalu(app, serwis_synchronizacji, zdarzenia):
    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [], sync_type='manual', auto_status_change=False)

        assert wynik['products_created'] == 0
        assert [z for z in zdarzenia if z != 'COMMIT'] == []


def test_import_awaria_sygnalu_nie_psuje_synchronizacji(app, serwis_synchronizacji, monkeypatch):
    def awaria(kod):
        raise RuntimeError('broker nie odpowiada')

    monkeypatch.setattr(realtime_service, 'publish_station_signal', awaria)
    with app.app_context():
        wynik = serwis_synchronizacji.process_orders_with_priority_logic(
            [zamowienie()], sync_type='manual', auto_status_change=False)

        assert wynik['success'] is True and wynik['products_created'] == 1
        assert ProductionProduct.query.count() == 1
