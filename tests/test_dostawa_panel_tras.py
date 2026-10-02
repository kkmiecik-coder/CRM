# -*- coding: utf-8 -*-
"""Panel tras po kroku 4.4 (spec 9.7): „Cofnij załadunek”, postęp „załadowano x/y · dostarczono a/b”, kiedy
załadowano i ruszono, trasa odhaczona w panelu, dostarczenie i „Zostaje” przy przystanku."""
from extensions import db
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
    assert dane['postep'] == {'przystanki': 3, 'zaladowane': 1, 'dostarczone': 0}   # anulowane się nie liczy
    assert (dane['zaladowana'], dane['wyjazd'], dane['odhaczona_w_panelu']) == (None, None, False)
    przystanki = _przystanki(dane)
    assert przystanki[zostaje.id]['dostawa'] == {
        'dostarczono': None,
        'zostaje': {'powod': 'brak_miejsca', 'etykieta': u'Brak miejsca', 'notatka': u'za długie'}}
    assert przystanki[pelne.id]['dostawa'] == {'dostarczono': None, 'zostaje': None}
    assert przystanki[czesc.id]['paczki']['zaladowane'] == 1


def test_szczegoly_trasy_w_drodze(app, client):
    a, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    b, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([a, b], status='w_trasie', loaded_at=T0, departed_at=T0)
    zaladuj_wprost(paczki_a + paczki_b, t)
    dostawa.dostarcz(t, a.id, worker_id=7, teraz=T0)
    db.session.commit()
    dane = client.get(BASE + '/routes/%d' % t.id).get_json()['route']
    assert dane['postep'] == {'przystanki': 2, 'zaladowane': 2, 'dostarczone': 1}
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
    assert wpis['postep'] == {'przystanki': 1, 'zaladowane': 1, 'dostarczone': 0}


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
    assert dane['postep'] == {'przystanki': 2, 'zaladowane': 0, 'dostarczone': 0}


def test_trasa_odhaczona_w_panelu(app):
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    t = trasa([order], status='w_trasie')
    dostawa.odhacz(t, [order.id], user_id=1, teraz=T0)
    db.session.commit()
    assert routes.serializuj_trase(t)['odhaczona_w_panelu'] is True
    t.completed_by = None                      # zamknął telefon (ostatnie „Dostarczone”)
    assert routes.serializuj_trase(t)['odhaczona_w_panelu'] is False
