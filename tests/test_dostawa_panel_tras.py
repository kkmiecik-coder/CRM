# -*- coding: utf-8 -*-
"""Panel tras po kroku 4.4 (spec 9.7): „Cofnij załadunek”, postęp „załadowano x/y · dostarczono a/b”, kiedy
załadowano i ruszono, trasa odhaczona w panelu, dostarczenie i „Zostaje” przy przystanku."""
from datetime import timedelta

from extensions import db
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import bl_sync, dostawa, routes
from tests.dostawa_pomocnicze import T0, trasa, zaladuj_wprost, zamowienie_z_paczkami
from tests.logistyka_fixtures import BASE, app, client  # noqa: F401


def _przystanki(dane):
    return {p['zamowienie']['id']: p['zamowienie'] for p in dane['przystanki']}


def test_cofnij_zaladunek_przez_api(app, client, monkeypatch):
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana', loaded_at=T0)
    zaladuj_wprost(lista_paczek, t)
    rid, oid = t.id, order.id
    r = client.post(BASE + '/routes/%d/unload' % rid)
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['route']['status'] == 'zatwierdzona'
    assert wywolania == [[oid]]
    r = client.post(BASE + '/routes/%d/unload' % rid)
    assert r.status_code == 409 and u'zatwierdzona' in r.get_json()['error']
    assert client.post(BASE + '/routes/999999/unload').status_code == 404


def test_szczegoly_trasy_w_zaladunku(app, client):
    pelne, paczki_pelne = zamowienie_z_paczkami()
    czesc, (c1, _c2) = zamowienie_z_paczkami()
    zostaje, _ = zamowienie_z_paczkami()
    anulowane, _ = zamowienie_z_paczkami(statusy=('anulowane',))
    t = trasa([pelne, czesc, zostaje, anulowane])
    zaladuj_wprost(paczki_pelne + [c1], t)
    dostawa.ustaw_zostaje(t, zostaje.id, 'brak_miejsca', u'za długie')
    db.session.commit()
    r = client.get(BASE + '/routes/%d' % t.id)
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()['route']
    # Anulowane się nie liczy.
    assert dane['postep'] == {'przystanki': 3, 'zaladowane': 1, 'dostarczone': 0, 'niedostarczone': 0, 'zdjete': 0}
    assert (dane['zaladowana'], dane['wyjazd'], dane['odhaczona_w_panelu']) == (None, None, False)
    przystanki = _przystanki(dane)
    assert przystanki[zostaje.id]['dostawa'] == {
        'dostarczono': None,
        'zostaje': {'powod': 'brak_miejsca', 'etykieta': u'Brak miejsca', 'notatka': u'za długie'}, 'cofnieto': None,
        'niedostarczono': None}
    assert przystanki[pelne.id]['dostawa'] == {'dostarczono': None, 'zostaje': None, 'cofnieto': None,
                                               'niedostarczono': None}
    assert przystanki[czesc.id]['paczki']['zaladowane'] == 1


def test_szczegoly_trasy_w_drodze(app, client):
    a, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    b, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([a, b], status='w_trasie', loaded_at=T0, departed_at=T0)
    zaladuj_wprost(paczki_a + paczki_b, t)
    dostawa.dostarcz(t, a.id, worker_id=7, teraz=T0)
    db.session.commit()
    dane = client.get(BASE + '/routes/%d' % t.id).get_json()['route']
    assert dane['postep'] == {'przystanki': 2, 'zaladowane': 2, 'dostarczone': 1, 'niedostarczone': 0, 'zdjete': 0}
    assert (dane['zaladowana'], dane['wyjazd']) == (T0.isoformat(), T0.isoformat())
    przystanki = _przystanki(dane)
    assert przystanki[a.id]['dostawa']['dostarczono'] == T0.isoformat()
    assert przystanki[b.id]['dostawa']['dostarczono'] is None


def test_lista_tras_ma_postep(app, client):
    order, lista_paczek = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost(lista_paczek, t)
    trasy = client.get(BASE + '/routes').get_json()['routes']
    wpis = next(x for x in trasy if x['id'] == t.id)
    assert wpis['postep'] == {'przystanki': 1, 'zaladowane': 1, 'dostarczone': 0, 'niedostarczone': 0, 'zdjete': 0}


def test_postep_nie_liczy_znacznika_innej_trasy(app, client):
    """Znacznik załadunku z innej trasy (zostaje np. po „Cofnij zatwierdzenie” w trakcie załadunku i zmianie trasy)
    nie robi z przystanku „załadowanego”; zamówienie bez paczek też nie."""
    z_obca_trasa, paczki_obce = zamowienie_z_paczkami()
    bez_paczek, _ = zamowienie_z_paczkami(paczek=0)
    inne, _ = zamowienie_z_paczkami()
    obca = trasa([inne])
    t = trasa([z_obca_trasa, bez_paczek])
    zaladuj_wprost(paczki_obce, obca)
    dane = client.get(BASE + '/routes/%d' % t.id).get_json()['route']
    assert dane['postep'] == {'przystanki': 2, 'zaladowane': 0, 'dostarczone': 0, 'niedostarczone': 0, 'zdjete': 0}


def test_trasa_odhaczona_w_panelu(app):
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    t = trasa([order], status='w_trasie')
    dostawa.odhacz(t, [order.id], user_id=1, teraz=T0)
    db.session.commit()
    assert routes.serializuj_trase(t)['odhaczona_w_panelu'] is True
    t.completed_by = None                      # zamknął telefon (ostatnie „Dostarczone”)
    assert routes.serializuj_trase(t)['odhaczona_w_panelu'] is False


def test_szczegoly_trasy_pokazuja_cofniecie_dostarczenia(app, client, monkeypatch):
    """U8 (oględziny 2.10): `zamowienie.dostawa.cofnieto` — czas ostatniego „Cofnij dostarczenie” zamówienia na TEJ
    trasie (wpis logu `dostarczenie_cofniete`); null, gdy przystanek jest znów dostarczony; wpis z innej trasy pominięty."""
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: None)
    a, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    b, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([a, b], status='w_trasie', loaded_at=T0, departed_at=T0)
    zaladuj_wprost(paczki_a + paczki_b, t)
    rid, ia, ib = t.id, a.id, b.id
    dostawa.dostarcz(t, ia, worker_id=7, teraz=T0)
    db.session.commit()

    def przystanki():
        r = client.get(BASE + '/routes/%d' % rid)
        assert r.status_code == 200, r.get_data()[:300]
        return _przystanki(r.get_json()['route'])

    assert przystanki()[ia]['dostawa']['cofnieto'] is None            # dostarczony, nigdy niecofnięty
    r = client.post(BASE + '/routes/%d/stops/%d/undo-delivered' % (rid, ia))
    assert r.status_code == 200, r.get_data()[:300]
    pierwsze = LogisticsLog.query.filter_by(order_id=ia, action='dostarczenie_cofniete').one().created_at
    assert _przystanki(r.get_json()['route'])[ia]['dostawa']['cofnieto'] == pierwsze.isoformat()   # odpowiedź akcji też

    # Znów dostarczony — ślad cofnięcia znika; drugie cofnięcie pokazuje NAJNOWSZY wpis.
    dostawa.dostarcz(t, ia, worker_id=7, teraz=pierwsze + timedelta(minutes=10))
    db.session.commit()
    assert przystanki()[ia]['dostawa'] == {'dostarczono': (pierwsze + timedelta(minutes=10)).isoformat(),
                                           'zostaje': None, 'cofnieto': None, 'niedostarczono': None}
    drugie = pierwsze + timedelta(minutes=20)
    dostawa.cofnij_dostarczenie(t, ia, user_id=1, teraz=drugie)
    db.session.commit()
    assert przystanki()[ia]['dostawa']['cofnieto'] == drugie.isoformat()

    # Wpis z innej trasy (to samo zamówienie b) nie liczy się dla tej trasy.
    db.session.add(LogisticsLog(order_id=ib, action='dostarczenie_cofniete', old_value='dostarczone',
                                new_value='zaladowane', route_id=rid + 1000, created_at=drugie))
    db.session.commit()
    assert przystanki()[ib]['dostawa']['cofnieto'] is None


def test_mapa_tras_oznacza_dostarczone_przystanki(app, client):
    """U4 (decyzja Konrada 2.10): GET /routes/map niesie przy przystanku `dostarczone` — mapa tras Dashboardu rysuje
    go zieloną stacją, jak oś w edytorze. Pole addytywne, bez dodatkowych zapytań (przystanki z selectinload)."""
    a, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    b, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([a, b], status='w_trasie', loaded_at=T0, departed_at=T0)
    zaladuj_wprost(paczki_a + paczki_b, t)
    rid, ia, ib = t.id, a.id, b.id
    dostawa.dostarcz(t, ia, worker_id=7, teraz=T0)
    db.session.commit()
    mapa = next(x for x in client.get(BASE + '/routes/map').get_json()['routes'] if x['id'] == rid)
    assert {p['order_id']: p['dostarczone'] for p in mapa['przystanki']} == {ia: True, ib: False}


# --- U10 (Ruling 32): niedostarczone na trasie w panelu ---------------------------------------------------------

def _w_drodze(ile=3):
    zamowienia = [zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane')) for _ in range(ile)]
    t = trasa([o for o, _ in zamowienia], status='w_trasie', loaded_at=T0, departed_at=T0)
    zaladuj_wprost([p for _, lista in zamowienia for p in lista], t)
    return t, [o for o, _ in zamowienia]


def test_szczegoly_niedostarczony_przystanek_i_historia(app, client):
    t, (a, b, c) = _w_drodze()
    rid, ia, ib, ic = t.id, a.id, b.id, c.id
    dostawa.nie_dostarcz(t, ia, 'brak_klienta', u'nikt', worker_id=7, teraz=T0)
    dostawa.nie_dostarcz(t, ib, 'odmowa', worker_id=7, teraz=T0)
    db.session.commit()
    dostawa.zdejmij_niedostarczone(t, ib, user_id=1, teraz=T0 + timedelta(hours=1))
    db.session.commit()
    dane = client.get(BASE + '/routes/%d' % rid).get_json()['route']
    assert dane['postep'] == {'przystanki': 2, 'zaladowane': 2, 'dostarczone': 0, 'niedostarczone': 2, 'zdjete': 1}
    przystanki = _przystanki(dane)
    assert przystanki[ia]['dostawa']['niedostarczono'] == {
        'powod': 'brak_klienta', 'etykieta': u'Brak klienta', 'notatka': u'nikt', 'kiedy': T0.isoformat()}
    assert przystanki[ic]['dostawa']['niedostarczono'] is None
    assert dane['niedostarczone_zdjete'] == [{
        'order_id': ib, 'numer': b.internal_order_number, 'klient': b.client_name, 'miasto': b.delivery_city,
        'powod': 'odmowa', 'etykieta': u'Odmowa przyjęcia', 'notatka': None, 'kiedy': T0.isoformat()}]
    # Lista tras — postęp z historią; mapa — niedostarczony przystanek oznaczony.
    wpis = next(x for x in client.get(BASE + '/routes').get_json()['routes'] if x['id'] == rid)
    assert wpis['postep'] == dane['postep']
    mapa = next(x for x in client.get(BASE + '/routes/map').get_json()['routes'] if x['id'] == rid)
    assert {p['order_id']: p['niedostarczone'] for p in mapa['przystanki']} == {ia: True, ic: False}


def test_panel_cofnij_niedostarczenie(app, client, monkeypatch):
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    t, (a, _b, _c) = _w_drodze()
    rid, ia = t.id, a.id
    dostawa.nie_dostarcz(t, ia, 'odmowa', worker_id=7, teraz=T0)
    db.session.commit()
    r = client.post(BASE + '/routes/%d/stops/%d/undo-not-delivered' % (rid, ia))
    assert r.status_code == 200, r.get_data()[:300]
    assert _przystanki(r.get_json()['route'])[ia]['dostawa']['niedostarczono'] is None
    wpis = LogisticsLog.query.filter_by(order_id=ia, action='niedostarczenie_cofniete').one()
    assert (wpis.old_value, wpis.worker_id) == ('odmowa', None)                # z panelu — bez kierowcy
    assert wywolania == []                                                   # Base. bez zmian
    r = client.post(BASE + '/routes/%d/stops/%d/undo-not-delivered' % (rid, ia))
    assert r.status_code == 200                                              # powtórka — bez zmian
    assert client.post(BASE + '/routes/999999/stops/%d/undo-not-delivered' % ia).status_code == 404


def test_panel_zdejmij_niedostarczone(app, client, monkeypatch):
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    t, (a, b, _c) = _w_drodze()
    rid, ia, ib = t.id, a.id, b.id
    dostawa.nie_dostarcz(t, ia, 'odmowa', worker_id=7, teraz=T0)
    db.session.commit()
    r = client.post(BASE + '/routes/%d/stops/%d/remove-not-delivered' % (rid, ib))
    assert r.status_code == 409 and u'tylko przystanek niedostarczony' in r.get_json()['error']
    r = client.post(BASE + '/routes/%d/stops/%d/remove-not-delivered' % (rid, ia))
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()['route']
    assert dane['status'] == 'w_trasie' and ia not in _przystanki(dane)
    assert [h['order_id'] for h in dane['niedostarczone_zdjete']] == [ia]
    assert wywolania == [[ia]]                                               # 417343 po commicie
    assert routes.przystanek_zamowienia(ia) is None
    assert client.post(BASE + '/routes/%d/stops/%d/remove-not-delivered' % (rid, ia)).status_code == 404


def test_odhacz_przez_api_zdejmuje_niedostarczone_z_historia(app, client):
    t, (a, b, c) = _w_drodze()
    rid, ia, ib, ic = t.id, a.id, b.id, c.id
    dostawa.nie_dostarcz(t, ia, 'brak_klienta', worker_id=7, teraz=T0)
    db.session.commit()
    r = client.post(BASE + '/routes/%d/complete' % rid, json={'delivered_order_ids': [ic]})
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()['route']
    assert (dane['status'], sorted(_przystanki(dane))) == ('wykonana', [ic])
    assert [(h['order_id'], h['powod']) for h in dane['niedostarczone_zdjete']] == [
        (ia, 'brak_klienta'), (ib, 'odhaczone_w_panelu')]
    assert dane['postep'] == {'przystanki': 1, 'zaladowane': 1, 'dostarczone': 1, 'niedostarczone': 2, 'zdjete': 2}


def test_robocza_nie_pokazuje_historii(app, client):
    order, _ = zamowienie_z_paczkami()
    t = trasa([order], status='robocza')
    dane = client.get(BASE + '/routes/%d' % t.id).get_json()['route']
    assert dane['niedostarczone_zdjete'] == []
