# -*- coding: utf-8 -*-
"""Ikona „etykiety paczek sprzed zmiany” w panelu Logistyki (etap 4, krok 4.2, spec 6.3)."""
import os
import re
from datetime import date, datetime

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import lista
from modules.production.models import ProductionPackage
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401

LOGISTYKA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'modules', 'production', 'logistics')


def _plik(*czesci):
    with open(os.path.join(LOGISTYKA, *czesci), encoding='utf-8') as f:
        return f.read()


def _wersja(html, plik):
    m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
    assert m, plik
    return m.group(1)


def _paczka(order, napis, voided=False, wydrukowana=True):
    p = ProductionPackage(order_id=order.id, seq=1, kind='paczka',
                          declared_at=datetime(2026, 9, 30, 10, 0),
                          label_printed_at=datetime(2026, 9, 30, 10, 1) if wydrukowana else None,
                          label_print_count=1 if wydrukowana else 0, label_delivery_text=napis,
                          voided_at=datetime(2026, 9, 30, 11, 0) if voided else None)
    db.session.add(p)
    db.session.commit()
    return p


def _wiersz(client, order):
    return next(w for w in client.get(BASE + '/orders').get_json()['orders'] if w['id'] == order.id)


@pytest.mark.parametrize('napis, voided, wydrukowana, ikona', [
    ('TRANSPORT WOODPOWER', False, True, False),
    ('KURIER', False, True, True),
    ('KURIER', True, True, False),          # unieważniona paczka się nie liczy
    (None, False, False, False),            # niewydrukowana
])
def test_ikona_etykiet_paczek(app, napis, voided, wydrukowana, ikona):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _paczka(order, napis, voided, wydrukowana)
    assert lista.serializuj(order)['etykiety_paczek_sprzed_zmiany'] is ikona


def test_bez_paczek_bez_ikony(app):
    assert lista.serializuj(zamowienie(sposob=s.KURIER))['etykiety_paczek_sprzed_zmiany'] is False


def test_ikona_po_dodaniu_do_trasy_i_po_wykonaniu_trasy(app, client):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _paczka(order, 'TRANSPORT WOODPOWER')
    assert _wiersz(client, order)['etykiety_paczek_sprzed_zmiany'] is False
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 7), date_to=date(2026, 10, 7))
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    db.session.commit()
    assert _wiersz(client, order)['etykiety_paczek_sprzed_zmiany'] is True     # etykieta bez trasy
    trasa.status = 'wykonana'                  # trasa wykonana nie trafia na etykietę
    db.session.commit()
    assert _wiersz(client, order)['etykiety_paczek_sprzed_zmiany'] is False


def test_ikona_znika_na_zamowieniu_zamknietym_w_logistyce(app):
    """Po wykonaniu trasy napis to „TRANSPORT WOODPOWER”, a na etykiecie „TRASA: …” — bez
    zamknięcia zamówienie z wykonanej trasy pokazywałoby ikonę na zawsze."""
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _paczka(order, 'TRASA: Rzeszow 07.10')
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 7), date_to=date(2026, 10, 7),
                  status='wykonana')
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    db.session.commit()
    # Bez zamknięcia: napis się różni (wykonana trasa nie jedzie), więc ikona świeci.
    assert lista.serializuj(order, trasa=trasa)['etykiety_paczek_sprzed_zmiany'] is True
    order.logistics_closed_at = datetime(2026, 10, 8, 12, 0)
    db.session.commit()
    assert lista.serializuj(order, trasa=trasa)['etykiety_paczek_sprzed_zmiany'] is False


def test_lista_czyta_paczki_jednym_zapytaniem(app, client):
    for _ in range(3):
        _paczka(zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)), 'KURIER')
    zapytania = []

    def nasluch(conn, cursor, statement, parameters, context, executemany):
        if 'FROM PROD_PACKAGES' in ' '.join(statement.upper().split()):
            zapytania.append(statement)

    event.listen(db.engine, 'before_cursor_execute', nasluch)
    try:
        wiersze = client.get(BASE + '/orders').get_json()['orders']
    finally:
        event.remove(db.engine, 'before_cursor_execute', nasluch)
    assert sum(1 for w in wiersze if w['etykiety_paczek_sprzed_zmiany']) == 3
    assert len(zapytania) == 1, zapytania


def test_hurt_czyta_paczki_jednym_zapytaniem(app, client):
    ids = [zamowienie(statusy=('czeka_na_pakowanie',)).id for _ in range(3)]
    zapytania = []

    def nasluch(conn, cursor, statement, parameters, context, executemany):
        if 'FROM PROD_PACKAGES' in ' '.join(statement.upper().split()):
            zapytania.append(statement)

    event.listen(db.engine, 'before_cursor_execute', nasluch)
    try:
        r = client.post(BASE + '/orders/delivery-method', json={'order_ids': ids, 'sposob': s.KURIER})
    finally:
        event.remove(db.engine, 'before_cursor_execute', nasluch)
    assert r.status_code == 200
    assert all(w['etykiety_paczek_sprzed_zmiany'] is False for w in r.get_json()['orders'])
    assert len(zapytania) == 1, zapytania


def test_ikona_i_legenda_w_panelu():
    js = _plik('static', 'js', 'logistics.js')
    assert 'w.etykiety_paczek_sprzed_zmiany' in js and "'fa-box'" in js
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert 'etykiety paczek sprzed zmiany' in html
    assert _wersja(html, 'js/logistics.js') != '20260928d'
