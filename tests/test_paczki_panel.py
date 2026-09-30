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
from modules.production.logistics.services import lista, routes
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


def _trasa(order, status, nazwa=u'Rzeszów'):
    """Trasa 7.10 z jednym przystankiem = `order` (w danym statusie)."""
    trasa = Route(name=nazwa, date_from=date(2026, 10, 7), date_to=date(2026, 10, 7), status=status)
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    db.session.commit()
    return trasa


def _zamknij(order):
    order.logistics_closed_at = datetime(2026, 10, 8, 12, 0)
    db.session.commit()


def _wiersz_zamkniety(client, order):
    """Wiersz z listy zamkniętych (wyszukiwanie po numerze — zamknięte wymagają frazy)."""
    wiersze = client.get(BASE + '/orders', query_string={
        'zamkniete': '1', 'q': order.internal_order_number}).get_json()['orders']
    return next(w for w in wiersze if w['id'] == order.id)


def _wiersz_pojedynczy(order):
    """Jak odświeżenie jednego wiersza po akcji w panel_api: trasa z trasy_zamowien([id])."""
    return lista.serializuj(order, trasa=routes.trasy_zamowien([order.id]).get(order.id))


def test_zamkniete_dowiezione_trasa_wykonana_bez_ikony(app):
    """Po wykonaniu trasy dzisiejszy napis (bez trasy aktywnej) to „TRANSPORT WOODPOWER”, a na
    etykiecie „TRASA: …”. Zamówienie otwarte pokazuje wtedy ikonę, zamknięte (dowiezione trasą)
    porównujemy z napisem liczonym z trasy wykonanej — więc nie świeci na zawsze."""
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _paczka(order, 'TRASA: Rzeszow 07.10')
    trasa = _trasa(order, 'wykonana')
    # Otwarte: napis się różni (wykonana trasa nie jedzie), więc ikona świeci.
    assert lista.serializuj(order, trasa=trasa)['etykiety_paczek_sprzed_zmiany'] is True
    _zamknij(order)
    assert lista.serializuj(order, trasa=trasa)['etykiety_paczek_sprzed_zmiany'] is False


def test_zamkniete_dowiezione_trasa_bez_ikony_na_liscie_i_w_pojedynczym_wierszu(app, client):
    """Trasa wykonana dociera do funkcji wszędzie, gdzie liczona jest ikona: na liście
    zamkniętych (trasy_zamowien nie filtruje statusu), przy odświeżeniu pojedynczego wiersza
    (panel_api: trasy_zamowien([id])) i w edytorze trasy (trasy_api podaje samą trasę)."""
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _paczka(order, 'TRASA: Rzeszow 07.10')
    trasa = _trasa(order, 'wykonana')
    _zamknij(order)
    assert _wiersz_zamkniety(client, order)['etykiety_paczek_sprzed_zmiany'] is False
    assert _wiersz_pojedynczy(order)['etykiety_paczek_sprzed_zmiany'] is False
    szczegoly = client.get(BASE + '/routes/%d' % trasa.id).get_json()['route']
    assert [p['zamowienie']['etykiety_paczek_sprzed_zmiany'] for p in szczegoly['przystanki']] == [False]
    # To samo zamówienie, gdyby było otwarte, świeciłoby (kontrola, że test coś rozróżnia).
    order.logistics_closed_at = None
    db.session.commit()
    assert _wiersz_pojedynczy(order)['etykiety_paczek_sprzed_zmiany'] is True


@pytest.mark.parametrize('nowy_sposob', [s.ODBIOR, s.KURIER])
def test_zamkniete_zmiana_sposobu_po_druku_zapala_ikone(app, client, nowy_sposob):
    """Etykieta „TRASA: …”, a zamówienie zamknięte ma już odbiór albo kuriera — prawdziwa
    zmiana po zamknięciu, ikona zostaje (na liście i w pojedynczym wierszu)."""
    order = zamowienie(sposob=nowy_sposob, statusy=('spakowane',))
    _paczka(order, 'TRASA: Rzeszow 07.10')
    _trasa(order, 'wykonana')
    _zamknij(order)
    assert _wiersz_zamkniety(client, order)['etykiety_paczek_sprzed_zmiany'] is True
    assert _wiersz_pojedynczy(order)['etykiety_paczek_sprzed_zmiany'] is True


def test_zamkniete_inna_trasa_niz_na_etykiecie_zapala_ikone(app, client):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _paczka(order, 'TRASA: Rzeszow 07.10')
    _trasa(order, 'wykonana', nazwa=u'Kraków')
    _zamknij(order)
    assert _wiersz_zamkniety(client, order)['etykiety_paczek_sprzed_zmiany'] is True
    assert _wiersz_pojedynczy(order)['etykiety_paczek_sprzed_zmiany'] is True


def test_zamkniete_etykieta_sprzed_trasy_zostaje_z_ikona(app, client):
    """Przypadek graniczny, świadomie zostawiony: etykieta wydrukowana, zanim zamówienie trafiło
    na trasę („TRANSPORT WOODPOWER”), a potem dowiezione trasą — napis naprawdę się różni."""
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _paczka(order, 'TRANSPORT WOODPOWER')
    _trasa(order, 'wykonana')
    _zamknij(order)
    assert _wiersz_zamkniety(client, order)['etykiety_paczek_sprzed_zmiany'] is True
    assert _wiersz_pojedynczy(order)['etykiety_paczek_sprzed_zmiany'] is True


@pytest.mark.parametrize('sposob, napis', [
    (s.KURIER, 'KURIER'),
    (s.ODBIOR, 'ODBIOR OSOBISTY'),
    (s.TRANSPORT, 'TRANSPORT WOODPOWER'),      # zamknięte bez trasy, sposób bez zmian
])
def test_zamkniete_bez_zmiany_sposobu_bez_ikony(app, client, sposob, napis):
    order = zamowienie(sposob=sposob, statusy=('spakowane',))
    _paczka(order, napis)
    _zamknij(order)
    assert _wiersz_zamkniety(client, order)['etykiety_paczek_sprzed_zmiany'] is False
    assert _wiersz_pojedynczy(order)['etykiety_paczek_sprzed_zmiany'] is False


@pytest.mark.parametrize('status', ['robocza', 'zatwierdzona'])
def test_otwarte_na_trasie_aktywnej_z_etykieta_trasy_bez_ikony(app, client, status):
    """Zamówienie otwarte — bez zmian: porównanie z napisem z trasy aktywnej."""
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _paczka(order, 'TRASA: Rzeszow 07.10')
    _trasa(order, status)
    assert _wiersz(client, order)['etykiety_paczek_sprzed_zmiany'] is False
    assert _wiersz_pojedynczy(order)['etykiety_paczek_sprzed_zmiany'] is False


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
