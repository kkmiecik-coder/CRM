# -*- coding: utf-8 -*-
"""
Poprawki backendu po przeglądzie całej gałęzi logistyki (28.09.2026). Punkt przeglądu
(I1, M3, …) w nagłówku każdej sekcji.
"""
import re

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync, geocoding, routes
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_tla(monkeypatch):
    """Bez wysyłki do Base. i bez wątków w tle — testy sprawdzają sam zapis."""
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: None)
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: True)
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: True)


# ── I1: zapis zamówienia z panelu = commit → blokada tras → dopiero odczyt ───

_ODCZYT_ZAMOWIEN = re.compile(r'^SELECT\b.*\bFROM PROD_ORDERS\b')


@pytest.fixture()
def dziennik(app, monkeypatch):
    """
    Zdarzenia żądania w kolejności: 'commit' (db.session.commit zakończony),
    'blokada' (wejście w routes.zablokuj_trasy), 'odczyt_zamowienia' (SELECT … FROM
    prod_orders wysłany do bazy) i 'sql' (każde inne zapytanie). SQLite nie odtworzy
    migawki REPEATABLE READ z MySQL, więc przypinamy samą kolejność.
    """
    zdarzenia = []
    oryg_commit = db.session.commit
    oryg_blokada = routes.zablokuj_trasy

    def commit():
        wynik = oryg_commit()
        zdarzenia.append('commit')
        return wynik

    def blokada(route=None):
        zdarzenia.append('blokada')
        return oryg_blokada(route)

    def nasluch(conn, cursor, statement, parameters, context, executemany):
        tekst = ' '.join(statement.upper().split())
        zdarzenia.append('odczyt_zamowienia' if _ODCZYT_ZAMOWIEN.search(tekst) else 'sql')

    monkeypatch.setattr(db.session, 'commit', commit)
    monkeypatch.setattr(routes, 'zablokuj_trasy', blokada)
    silnik = db.engine
    event.listen(silnik, 'before_cursor_execute', nasluch)
    yield zdarzenia
    event.remove(silnik, 'before_cursor_execute', nasluch)


def _sprawdz_kolejnosc(dziennik):
    zdarzenia = [z for z in dziennik if z != 'sql']
    assert zdarzenia[:3] == ['commit', 'blokada', 'odczyt_zamowienia'], dziennik
    # Między commitem a blokadą ani jednego zapytania: każdy zwykły SELECT (także
    # dociągnięcie wygaszonego atrybutu ORM) utworzyłby migawkę jeszcze przed blokadą.
    assert dziennik[dziennik.index('commit') + 1] == 'blokada', dziennik


def _sposob(client, oid):
    return client.post(BASE + '/orders/delivery-method', json={'order_ids': [oid], 'sposob': s.TRANSPORT})


def _wydanie(client, oid):
    return client.post(BASE + '/orders/%d/handed-over' % oid)


def _adres(client, oid):
    return client.put(BASE + '/orders/%d/address' % oid,
                      json={'adres': 'Nowa 1', 'kod': '30-001', 'miasto': 'Kraków'})


@pytest.mark.parametrize('zadanie, kolumny', [
    (_sposob, {}),
    (_wydanie, {'sposob': s.ODBIOR, 'statusy': ('spakowane',)}),
    (_adres, {}),
], ids=['sposob-dostawy', 'wydane-klientowi', 'adres'])
def test_i1_zapis_commit_blokada_potem_odczyt_zamowienia(client, app, dziennik, zadanie, kolumny):
    """I1: migawka REPEATABLE READ powstaje przy pierwszym zwykłym odczycie transakcji
    (w aplikacji już w before_request) — zapis zaczyna transakcję od nowa, bierze blokadę
    tras i dopiero wtedy czyta zamówienie, więc widzi zmiany poprzedniego piszącego."""
    with app.app_context():
        oid = zamowienie(**kolumny).id
    dziennik.clear()
    r = zadanie(client, oid)
    assert r.status_code == 200, r.get_json()
    _sprawdz_kolejnosc(dziennik)


def test_i1_hurt_kilku_zamowien_tez_zaczyna_od_commitu_i_blokady(client, app, dziennik):
    with app.app_context():
        ids = [zamowienie().id, zamowienie().id]
    dziennik.clear()
    r = client.post(BASE + '/orders/delivery-method', json={'order_ids': ids, 'sposob': s.KURIER})
    assert r.status_code == 200 and sorted(r.get_json()['zmienione']) == sorted(ids)
    _sprawdz_kolejnosc(dziennik)


def test_i1_wydane_klientowi_bierze_blokade_tras(client, app, monkeypatch):
    """I1: „Wydane klientowi” brało decyzję bez blokady — na stanie sprzed równoległej
    zmiany sposobu (np. na kuriera z przepakowaniem) mogło wydać i zamknąć zamówienie."""
    wywolania = []
    oryginal = routes.zablokuj_trasy

    def podglad(route=None):
        wywolania.append(route)
        return oryginal(route)

    monkeypatch.setattr(routes, 'zablokuj_trasy', podglad)
    with app.app_context():
        oid = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',)).id
    r = client.post(BASE + '/orders/%d/handed-over' % oid)
    assert r.status_code == 200 and r.get_json()['order']['wydane'] is not None
    assert wywolania == [None]


def test_i1_wydanie_nieznanego_zamowienia_to_dalej_404(client):
    assert client.post(BASE + '/orders/999999/handed-over').status_code == 404


@pytest.mark.parametrize('zadanie', [
    lambda c, oid: c.post(BASE + '/orders/delivery-method', json={'order_ids': [], 'sposob': s.KURIER}),
    lambda c, oid: c.post(BASE + '/orders/delivery-method', json=[1, 2]),
    lambda c, oid: c.put(BASE + '/orders/%d/address' % oid, json=[1, 2]),
], ids=['pusty-hurt', 'hurt-lista', 'adres-lista'])
def test_i1_zle_cialo_odrzucone_przed_commitem_i_blokada(client, app, dziennik, zadanie):
    """Walidacja ciała żądania idzie PRZED pomocnikiem — złe dane nie biorą blokady tras."""
    with app.app_context():
        oid = zamowienie().id
    dziennik.clear()
    assert zadanie(client, oid).status_code == 422
    assert 'commit' not in dziennik and 'blokada' not in dziennik
