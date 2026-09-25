# -*- coding: utf-8 -*-
from datetime import date, datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync, routes
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_base(monkeypatch):
    wywolane = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolane.append(list(ids)))
    return wywolane


def test_lista_otwartych_z_nieustawionymi_na_gorze(client, app):
    with app.app_context():
        a = zamowienie(sposob=s.KURIER)
        a.products[0].deadline_date = date(2026, 9, 26)
        b = zamowienie()
        b.products[0].deadline_date = date(2026, 10, 30)
        zamowienie(sposob=s.KURIER, statusy=('spakowane',),
                   logistics_closed_at=datetime(2026, 9, 1))  # zamknięte — niewidoczne
        db.session.commit()
        numery = [a.internal_order_number, b.internal_order_number]
    dane = client.get(BASE + '/orders').get_json()
    assert [o['numer'] for o in dane['orders']] == [numery[1], numery[0]]
    assert dane['liczniki']['brak'] == 1 and dane['liczniki'][s.KURIER] == 1


def test_wiersz_listy(client, app):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_lakiernie', 'czeka_na_pakowanie'),
                           delivery_method='Odbiór osobisty')
        order.products[0].label_printed_at = datetime(2026, 9, 24, 8, 0)
        order.override_delivery_method = s.KURIER
        order.delivery_method_set_at = datetime(2026, 9, 24, 9, 0)
        db.session.commit()
    wiersz = client.get(BASE + '/orders').get_json()['orders'][0]
    assert wiersz['sposob'] == s.KURIER and wiersz['sposob_etykieta'] == 'Kurier'
    assert wiersz['podpowiedz'] == s.ODBIOR
    assert wiersz['metoda_z_base'] == 'Odbiór osobisty'
    assert wiersz['etap']['status'] == 'czeka_na_lakiernie'
    assert wiersz['m3'] == pytest.approx(0.096)  # 2 pozycje × 0.024 × 2 szt.
    assert wiersz['etykiety_sprzed_zmiany'] is True


def test_filtr_i_wyszukiwarka(client, app):
    with app.app_context():
        zamowienie(sposob=s.KURIER, miasto='Tarnów')
        zamowienie(miasto='Rzeszów')
    assert len(client.get(BASE + '/orders?sposob=brak').get_json()['orders']) == 1
    assert client.get(BASE + '/orders?q=Tarn').get_json()['orders'][0]['miasto'] == 'Tarnów'


def test_zamkniete_tylko_z_wyszukiwaniem(client, app):
    with app.app_context():
        zamowienie(sposob=s.KURIER, statusy=('spakowane',), miasto='Gdańsk',
                   logistics_closed_at=datetime(2026, 9, 1))
    assert client.get(BASE + '/orders?zamkniete=1').status_code == 422
    dane = client.get(BASE + '/orders?zamkniete=1&q=Gda').get_json()
    assert dane['orders'][0]['zamkniete'] is True


def test_zamkniete_z_filtrem_sposobu_i_wyszukiwarka(client, app):
    """
    R3: w SQLAlchemy < 2.0 Query.filter() wołane PO limit() rzuca
    InvalidRequestError. `zamkniete=1` dokłada order_by/limit — filtry q i sposob
    muszą trafić do zapytania PRZED nimi, inaczej to żądanie (zamkniete razem
    z q i sposob naraz) skończyłoby się 500, nie 200 z poprawnie zawężoną listą.
    """
    with app.app_context():
        kurier = zamowienie(sposob=s.KURIER, statusy=('spakowane',), miasto='Gdynia',
                            logistics_closed_at=datetime(2026, 9, 2))
        brak = zamowienie(statusy=('spakowane',), miasto='Gdynia',
                          logistics_closed_at=datetime(2026, 9, 2))
        numer_kurier = kurier.internal_order_number
        numer_brak = brak.internal_order_number

    r = client.get(BASE + '/orders?zamkniete=1&q=Gdy&sposob=' + s.KURIER)
    assert r.status_code == 200
    assert [o['numer'] for o in r.get_json()['orders']] == [numer_kurier]

    r = client.get(BASE + '/orders?zamkniete=1&q=Gdy&sposob=brak')
    assert r.status_code == 200
    assert [o['numer'] for o in r.get_json()['orders']] == [numer_brak]


def test_hurtowe_ustawienie_sposobu(client, app, bez_base):
    with app.app_context():
        ids = [zamowienie().id, zamowienie().id]
    r = client.post(BASE + '/orders/delivery-method',
                    json={'order_ids': ids, 'sposob': s.TRANSPORT})
    dane = r.get_json()
    assert r.status_code == 200 and sorted(dane['zmienione']) == sorted(ids)
    assert bez_base == [sorted(ids)] or bez_base == [ids]
    with app.app_context():
        assert all(ProductionOrder.query.get(i).override_delivery_method == s.TRANSPORT
                   for i in ids)


def test_hurtowe_ustawienie_bierze_blokade_tras_przed_petla(client, app, bez_base, monkeypatch):
    """fix-1, Ruling A7: POST /orders/delivery-method bierze globalną blokadę tras
    PRZED pętlą po zamówieniach (kolejność „trasa najpierw" — inaczej pętla mogłaby
    trzymać blokady wierszy pozycji i czekać na blokadę trasy, podczas gdy
    zatwierdzenie trasy czekałoby na te same pozycje — zakleszczenie).

    (fix-2, N1): odkąd `ustaw_sposob_dostawy` → `_przystanek_do_zmiany` TEŻ bierze
    blokadę jako pierwszą rzecz — dla KAŻDEGO zamówienia, nawet bez trasy — na 2
    zamówienia wychodzą 3 wywołania: 1 z tej funkcji (przed pętlą) + po 1 na
    zamówienie. Wszystkie z `route=None` (żadne z dwóch zamówień nie ma trasy),
    więc kolejność „ta funkcja najpierw" nie da się tu odróżnić po samej wartości
    argumentu — ale to i tak jest re-entrantnie bezpieczne (patrz docstring
    zablokuj_trasy), a liczba wywołań przypina, że nic nie ubyło ani nie przybyło."""
    wywolania = []
    oryginal = routes.zablokuj_trasy

    def podglad(route=None):
        wywolania.append(route.id if route is not None else None)
        return oryginal(route)

    monkeypatch.setattr(routes, 'zablokuj_trasy', podglad)
    with app.app_context():
        ids = [zamowienie().id, zamowienie().id]
    r = client.post(BASE + '/orders/delivery-method',
                    json={'order_ids': ids, 'sposob': s.TRANSPORT})
    assert r.status_code == 200
    assert wywolania == [None, None, None]


def test_hurt_z_czesciowa_odmowa(client, app):
    with app.app_context():
        ok = zamowienie().id
        wydane = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',),
                            handed_over_at=datetime(2026, 9, 20)).id
    dane = client.post(BASE + '/orders/delivery-method',
                       json={'order_ids': [ok, wydane], 'sposob': s.KURIER}).get_json()
    assert dane['zmienione'] == [ok]
    assert dane['bledy'][0]['order_id'] == wydane


@pytest.mark.parametrize('body', [
    {'order_ids': [], 'sposob': 'kurier_baselinker'},
    {'order_ids': [1], 'sposob': 'DPD'},
    {'order_ids': list(range(501)), 'sposob': 'kurier_baselinker'},
    # F1 (fix round 1): elementy order_ids inne niż int trafiały surowe do
    # Query.filter(ProductionOrder.id.in_(ids)) i SQLAlchemy rzucało
    # ProgrammingError z bazy (500) zamiast czystego 422.
    {'order_ids': [{'a': 1}], 'sposob': 'kurier_baselinker'},
    {'order_ids': ['abc'], 'sposob': 'kurier_baselinker'},
    {'order_ids': [None], 'sposob': 'kurier_baselinker'},
    {'order_ids': [True], 'sposob': 'kurier_baselinker'},
])
def test_walidacja_hurtu(client, body):
    assert client.post(BASE + '/orders/delivery-method', json=body).status_code == 422


def test_wydane_klientowi(client, app):
    with app.app_context():
        oid = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',)).id
        nie = zamowienie(sposob=s.KURIER, statusy=('spakowane',)).id
    r = client.post(BASE + '/orders/%d/handed-over' % oid)
    assert r.status_code == 200 and r.get_json()['order']['wydane'] is not None
    r = client.post(BASE + '/orders/%d/handed-over' % nie)
    assert r.status_code == 409 and r.get_json()['success'] is False


def test_zakladka_renderuje_sie(client):
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    assert b'id="logistics-root"' in r.data


# ── Poprawki po przeglądzie całej gałęzi ────────────────────────────────────

@pytest.mark.parametrize('body', [[1, 2], 'kurier_baselinker', 5])
def test_cialo_json_inne_niz_obiekt_to_422(client, body):
    """M1 (sonda P1): tablica/skalar w ciele → AttributeError na .get() → 500."""
    assert client.post(BASE + '/orders/delivery-method', json=body).status_code == 422


@pytest.mark.parametrize('wartosc', ['', 'DPD'])
def test_wartosc_spoza_sposobow_to_nie_ustawiono_wszedzie(client, app, wartosc):
    """M2 (sonda P3): wartość spoza SPOSOBY (pusty tekst, stary śmieć) licznik zakładki
    i 409 tabletu traktują jak „Nie ustawiono” (normalizuj), a filtr `brak` i bramka
    dashboardu liczyły tylko IS NULL — cztery definicje się rozjeżdżały."""
    from modules.production.logistics.services import lista
    with app.app_context():
        numer = zamowienie(sposob=wartosc, statusy=('czeka_na_pakowanie',)).internal_order_number
    dane = client.get(BASE + '/orders').get_json()
    assert dane['liczniki']['brak'] == 1
    assert [o['numer'] for o in client.get(BASE + '/orders?sposob=brak').get_json()['orders']] \
        == [numer]
    with app.app_context():
        assert lista.liczba_bez_sposobu() == 1


def test_bramka_dashboardu_liczy_przez_liste_logistyki():
    """M2: bramka „Bez sposobu dostawy: N” ma tę samą definicję co filtr `brak`."""
    import os
    sciezka = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'modules', 'production', 'routers', 'api', 'dashboard_api.py')
    kod = open(sciezka, encoding='utf-8').read()
    assert 'liczba_bez_sposobu()' in kod
    assert 'override_delivery_method.is_(None)' not in kod


def test_bramka_pomija_zamkniete_i_anulowane(app):
    from modules.production.logistics.services import lista
    with app.app_context():
        zamowienie(statusy=('czeka_na_pakowanie',))                     # liczy się
        zamowienie(statusy=('anulowane',))                              # same anulowane
        zamowienie(statusy=('spakowane',), logistics_closed_at=datetime(2026, 9, 1))
        zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))    # ma sposób
        assert lista.liczba_bez_sposobu() == 1


# M4 (spec 13): prawdziwa kontrola dostępu — bez LOGIN_DISABLED i bez podmiany
# require_module_access. Endpointy API odpowiadają JSON-em, nie przekierowaniem HTML.
TRASY_PANELU = [
    ('get', '/tab-content'),
    ('get', '/orders'),
    ('post', '/orders/delivery-method'),
    ('post', '/orders/1/handed-over'),
    # Etap 2 (M7): geokoder i korekta pinezki pod tą samą kontrolą dostępu.
    ('post', '/geocode'),
    ('put', '/orders/1/geo'),
    ('post', '/orders/1/geo/reset'),
]


@pytest.fixture()
def prawdziwy_dostep(app, monkeypatch):
    import modules.users.decorators as decorators
    from modules.users.decorators import permission_required
    monkeypatch.setattr(decorators, 'require_module_access',
                        permission_required.require_module_access)
    app.config['LOGIN_DISABLED'] = False
    app.secret_key = 'klucz-sesji-testow-logistyki-' + 'x' * 16
    return app


@pytest.mark.parametrize('metoda, sciezka', TRASY_PANELU)
def test_bez_sesji_401_json(prawdziwy_dostep, metoda, sciezka):
    r = getattr(prawdziwy_dostep.test_client(), metoda)(BASE + sciezka)
    assert r.status_code == 401
    assert r.get_json() == {'error': 'unauthorized'}


@pytest.mark.parametrize('metoda, sciezka', TRASY_PANELU)
def test_bez_uprawnien_do_produkcji_403_json(prawdziwy_dostep, monkeypatch, metoda, sciezka):
    from modules.users.models import User
    from modules.users.services.permission_service import PermissionService
    with prawdziwy_dostep.app_context():
        db.session.add(User(email='logistyk@woodpower.pl', password='x', active=True))
        db.session.commit()
    monkeypatch.setattr(PermissionService, 'user_has_module_access',
                        staticmethod(lambda uid, module_key: False))
    klient = prawdziwy_dostep.test_client()
    with klient.session_transaction() as sesja:
        sesja['user_email'] = 'logistyk@woodpower.pl'
    r = getattr(klient, metoda)(BASE + sciezka)
    assert r.status_code == 403
    assert r.get_json() == {'error': 'module_access_denied'}


def test_hurt_laduje_pozycje_jednym_zapytaniem(client, app):
    """M5: pozycje zamówień ładowane selectinload-em, nie zamówienie po zamówieniu
    (dwa razy: przy zmianie i przy serializacji odpowiedzi)."""
    from sqlalchemy import event
    with app.app_context():
        ids = [zamowienie(statusy=('czeka_na_pakowanie', 'czeka_na_wyciecie')).id
               for _ in range(4)]
        engine = db.engine
    zapytania = []

    def nasluch(conn, cursor, statement, parameters, context, executemany):
        gorna = ' '.join(statement.upper().split())
        if gorna.startswith('SELECT') and 'FROM PROD_PRODUCTS' in gorna:
            zapytania.append(gorna)

    event.listen(engine, 'before_cursor_execute', nasluch)
    try:
        r = client.post(BASE + '/orders/delivery-method',
                        json={'order_ids': ids, 'sposob': s.TRANSPORT})
    finally:
        event.remove(engine, 'before_cursor_execute', nasluch)
    assert r.status_code == 200 and sorted(r.get_json()['zmienione']) == sorted(ids)
    assert len(zapytania) == 2, zapytania


@pytest.mark.parametrize('fraza, oczekiwane', [
    ('y_S', ['Nowy_Sącz']),   # `_` dosłownie, nie „dowolny znak”
    ('_', ['Nowy_Sącz']),
    ('%', ['Kraków%']),        # `%` dosłownie, nie „wszystko”
    ('\\', ['Tarnów\\Mościce']),  # sam znak ucieczki też escapowany
])
def test_wyszukiwarka_traktuje_znaki_like_doslownie(client, app, fraza, oczekiwane):
    """T8: `%`, `_` i `\\` we frazie są escapowane (ESCAPE '\\')."""
    from urllib.parse import quote
    with app.app_context():
        for miasto in ('Nowy_Sącz', 'NowyXSącz', 'Kraków%', 'Tarnów\\Mościce'):
            zamowienie(miasto=miasto)
    wynik = client.get(BASE + '/orders?q=' + quote(fraza)).get_json()['orders']
    assert sorted(o['miasto'] for o in wynik) == oczekiwane


def test_nieznany_status_pozycji_to_najwczesniejszy_etap(client, app):
    """I2b: produkt zapisany przez stary kod jako `czeka_na_logistyke` (okno wdrożenia)
    ma być widoczny jako anomalia — najwcześniejszy etap, nie „Spakowane”."""
    from modules.production.logistics.services import lista
    assert lista._ranga('czeka_na_logistyke') == -1
    assert lista._ranga('nieznany') < lista._ranga('wstrzymane')
    with app.app_context():
        zamowienie(statusy=('spakowane', 'czeka_na_logistyke'))
    wiersz = client.get(BASE + '/orders').get_json()['orders'][0]
    assert wiersz['etap']['status'] == 'czeka_na_logistyke'
