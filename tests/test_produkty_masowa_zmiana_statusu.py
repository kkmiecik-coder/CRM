# -*- coding: utf-8 -*-
"""
Masowa zmiana statusu produktów.

Dziś ten endpoint NIE MA żadnej walidacji — przypisuje surowy string
z requestu do product.current_status (products_api.py:1286) — a
db.session.commit() stoi POZA pętlą try (:1316). Enum SQLAlchemy nie sprawdza
wartości po stronie Pythona przy ZAPISIE (validate_strings domyślnie False),
więc błąd nie pojawia się w kodzie, tylko w bazie: po zwężeniu enuma
(czeka_na_wykanczanie -> czeka_na_krawedzie) wysłanie starego statusu wywala
na MySQL-u CAŁY batch błędem 1265 (Data truncated), łącznie z pozycjami,
które w ogóle nie były problemem.

Na SQLite Enum ma create_constraint=False (domyślne w SQLAlchemy 1.4), więc
baza nic nie sprawdzi — sprawdzone na kontenerze: dziś taki request kończy
się HTTP 200 i processed_count=1. Właśnie dlatego walidacja musi siedzieć
w kodzie i mieć własny test.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.models import ProductionProduct
from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401


def _masowo(client, ids, status):
    return client.post(BASE + '/products/bulk-action', json={
        'action': 'update_status',
        'product_ids': ids,
        'parameters': {'new_status': status},
    })


def test_nieznany_status_odrzucony_przed_zapisem(client, app):
    pid, _ = produkt(app, status='czeka_na_krawedzie')
    r = _masowo(client, [pid], 'czeka_na_wykanczanie')
    assert r.status_code == 400, r.get_data()[:500]
    assert r.get_json()['success'] is False
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_krawedzie'


def test_jeden_zly_status_nie_psuje_calego_batcha(client, app):
    """Walidacja stoi PRZED pętlą — żadna pozycja nie zostaje ruszona."""
    a, _ = produkt(app, status='czeka_na_krawedzie', numer='25/00001')
    b, _ = produkt(app, status='czeka_na_krawedzie', numer='25/00002')
    r = _masowo(client, [a, b], 'zupelnie_nieistniejacy_status')
    assert r.status_code == 400
    with app.app_context():
        for pid in (a, b):
            assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_krawedzie'


def test_status_krawedzi_przechodzi(client, app):
    pid, _ = produkt(app, status='czeka_na_formatowanie')
    r = _masowo(client, [pid], 'czeka_na_krawedzie')
    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['processed_count'] == 1
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_krawedzie'


def test_status_lakierni_przechodzi(client, app):
    pid, _ = produkt(app, status='czeka_na_formatowanie')
    r = _masowo(client, [pid], 'czeka_na_lakiernie')
    assert r.status_code == 200, r.get_data()[:500]
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_lakiernie'


def test_inne_akcje_nie_wymagaja_statusu(client, app):
    """Walidacja obowiązuje wyłącznie akcję update_status."""
    pid, _ = produkt(app)
    r = client.post(BASE + '/products/bulk-action', json={
        'action': 'update_priority',
        'product_ids': [pid],
        'parameters': {'new_priority': 42},
    })
    assert r.status_code == 200, r.get_data()[:500]
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).priority_rank == 42


@pytest.mark.parametrize('status', ['zweryfikowane', 'zaladowane', 'dostarczone'])
def test_statusow_logistyki_nie_ustawia_sie_recznie(client, app, status):
    """Spec 8.6: nowe statusy nadaje tylko logistyka — hurtowa zmiana ich nie oferuje."""
    pid, _ = produkt(app, status='czeka_na_pakowanie')
    r = _masowo(client, [pid], status)
    assert r.status_code == 400
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_pakowanie'


def test_reczna_zmiana_statusu_wola_regule_uniewaznienia(client, app, monkeypatch):
    from modules.production.logistics.services import weryfikacja
    wolania = []
    monkeypatch.setattr(weryfikacja, 'uniewaznij_etapy',
                        lambda order, teraz, powod, **k: wolania.append((order.id, powod)) or False)
    pid, _ = produkt(app, status='spakowane')
    assert _masowo(client, [pid], 'czeka_na_pakowanie').status_code == 200
    with app.app_context():
        order_id = db.session.get(ProductionProduct, pid).order_id
    assert wolania == [(order_id, u'zmiana statusu w panelu')]


def test_reczna_zmiana_statusu_uniewaznia_zamowienia_w_stalej_kolejnosci(client, app, monkeypatch):
    """
    Reguła unieważniania zapisuje wiersz zamówienia i bierze blokady paczek, więc dwa równoległe
    hurtowe zapisy na nakładających się zamówieniach muszą je brać w tej samej kolejności
    (rosnące id), niezależnie od kolejności product_ids w żądaniu — inaczej MySQL 1213.
    """
    from modules.production.logistics.services import weryfikacja
    wolania = []
    monkeypatch.setattr(weryfikacja, 'uniewaznij_etapy',
                        lambda order, teraz, powod, **k: wolania.append(order.id) or False)
    pids = [produkt(app, status='spakowane', numer='25/0010{}'.format(n))[0] for n in range(6)]
    # Żądanie w odwrotnej kolejności niż powstawały zamówienia.
    assert _masowo(client, list(reversed(pids)), 'czeka_na_pakowanie').status_code == 200
    with app.app_context():
        id_zamowien = sorted(db.session.get(ProductionProduct, pid).order_id for pid in pids)
    assert wolania == id_zamowien


def test_hurt_do_produkcji_uniewaznia_etapy_prawdziwa_regula(client, app):
    """
    Styk zadań (fala końcowa 4.3, F6a): hurtowa zmiana statusu z PRAWDZIWĄ regułą unieważnienia etapów,
    bez podmiany `uniewaznij_etapy`. Zamówienie ma dwie pozycje 'zweryfikowane', zadeklarowane i sprawdzone
    paczki. Hurt cofa jedną pozycję do produkcji: paczki tracą ważność, zamówienie traci weryfikację,
    druga pozycja wraca do 'spakowane' i zostaje wpis logu reguły.
    """
    from datetime import datetime

    from modules.production.logistics import sposoby
    from modules.production.logistics.models import LogisticsLog
    from modules.production.models import LabelPrintJob, ProductionOrder, ProductionPackage
    chwila = datetime(2026, 10, 1, 8, 0)
    with app.app_context():
        # Tych tabel nie zakłada wspólny zestaw tego modułu testów (reguła zapisuje log i paczki).
        db.metadata.create_all(bind=db.engine, tables=[
            LogisticsLog.__table__, ProductionPackage.__table__, LabelPrintJob.__table__])
    pierwsza_id, _ = produkt(app, status='zweryfikowane', numer='25/00301')
    with app.app_context():
        pierwsza = db.session.get(ProductionProduct, pierwsza_id)
        order = pierwsza.order
        druga = ProductionProduct(
            order_id=order.id, short_product_id='2500301_2', product_sequence_in_order=2,
            original_product_name='Blat dębowy', current_status='zweryfikowane', quantity=1, volume_m3=0.1)
        db.session.add(druga)
        order.override_delivery_method = sposoby.KURIER
        order.verified_at, order.verified_by_worker_id = chwila, 7
        order.packages_declared_at, order.logistics_closed_at = chwila, chwila
        db.session.add_all([ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=chwila,
                                              verified_at=chwila, verified_method='skan')
                            for i in (1, 2)])
        db.session.commit()
        order_id, druga_id = order.id, druga.id

    r = _masowo(client, [pierwsza_id], 'czeka_na_pakowanie')
    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['processed_count'] == 1

    with app.app_context():
        order = db.session.get(ProductionOrder, order_id)
        assert db.session.get(ProductionProduct, pierwsza_id).current_status == 'czeka_na_pakowanie'
        assert db.session.get(ProductionProduct, druga_id).current_status == 'spakowane'   # wraca ze zweryfikowanych
        paczki = ProductionPackage.query.filter_by(order_id=order_id).all()
        assert len(paczki) == 2 and all(p.voided_at is not None for p in paczki)
        assert order.verified_at is None and order.verified_by_worker_id is None
        assert order.packages_declared_at is None
        assert order.logistics_closed_at is None          # kurier nie jest już w całości po spakowaniu
        wpisy = {w.action: w for w in LogisticsLog.query.filter_by(order_id=order_id)}
        assert set(wpisy) == {'weryfikacja_cofnieta', 'paczki'}
        assert wpisy['weryfikacja_cofnieta'].note == u'zmiana statusu w panelu'
        assert wpisy['weryfikacja_cofnieta'].user_id == 1
