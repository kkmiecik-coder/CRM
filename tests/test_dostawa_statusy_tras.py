# -*- coding: utf-8 -*-
"""Statusy tras załadowana i w trasie w istniejącym backendzie (logistyka etap 4, krok 4.4, spec 4.3, 4.5, 9.3,
9.7 i 11): blokady zmian zamówień z takich tras, zajętość, tablet, Routimo, kolejność listy tras, etap „W trasie”,
znaczniki załadunku w regule unieważniania i w cofnięciu weryfikacji, statusy Base. Dostawy w raportach."""
import os

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import bl_sync, delivery, geocoding, lista, paczki, routes, weryfikacja
from modules.production.logistics.services.delivery import LogistykaBlad
from tests.dostawa_pomocnicze import DZIEN, T0, trasa, zaladuj_wprost, zamowienie_z_paczkami
from tests.logistyka_fixtures import BASE, app, client, kierowca, pojazd  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bez_zaladunku(p):
    """Wszystkie cztery znaczniki załadunku paczki puste."""
    return (p.loaded_at, p.loaded_by_worker_id, p.loaded_method, p.loaded_route_id) == (None, None, None, None)


@pytest.mark.parametrize('status, fragment', [
    ('zaladowana', u'najpierw cofnij załadunek'),
    ('w_trasie', u'gdy kierowca rozliczy przystanek'),
])
def test_zmiana_adresu_zamowienia_z_trasy_zaladowanej_i_w_trasie_409(app, status, fragment):
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    t = trasa([order], status=status)
    with pytest.raises(LogistykaBlad) as e:
        delivery.zmien_adres(order, u'ul. Nowa 1', '35-001', u'Rzeszów')
    assert e.value.status == 409
    assert t.name in e.value.komunikat and fragment in e.value.komunikat


def test_zmiana_adresu_zamowienia_dostarczonego_na_trasie_w_drodze_409(app):
    """Przystanek już dostarczony, a trasa jeszcze w drodze — zamówienie jest u klienta, jak na trasie wykonanej."""
    order, _ = zamowienie_z_paczkami(statusy=('dostarczone',))
    t = trasa([order], status='w_trasie')
    t.stops[0].delivered_at = T0
    db.session.commit()
    with pytest.raises(LogistykaBlad) as e:
        delivery.zmien_adres(order, u'ul. Nowa 1', '35-001', u'Rzeszów')
    assert e.value.status == 409 and u'zostało dostarczone' in e.value.komunikat


@pytest.mark.parametrize('status, fragment', [
    ('zaladowana', u'najpierw cofnij załadunek'),
    ('w_trasie', u'gdy kierowca rozliczy przystanek'),
])
@pytest.mark.parametrize('nowy', [s.KURIER, s.ODBIOR, s.BRAK])
def test_zmiana_sposobu_zamowienia_z_trasy_zaladowanej_i_w_trasie_409(app, status, fragment, nowy):
    """Zamówienie po doróbce (pozycje znowu „spakowane”) zostaje na trasie załadowanej albo w drodze — zdjęcie
    go z trasy zmianą sposobu dostawy odmawia, przystanek i sposób zostają."""
    order, _ = zamowienie_z_paczkami(statusy=('spakowane', 'spakowane'), zweryfikowane=False)
    t = trasa([order], status=status)
    with pytest.raises(LogistykaBlad) as e:
        delivery.ustaw_sposob_dostawy(order, nowy, teraz=T0)
    assert e.value.status == 409
    assert t.name in e.value.komunikat and fragment in e.value.komunikat
    assert order.override_delivery_method == s.TRANSPORT
    assert routes.przystanek_zamowienia(order.id).route_id == t.id


@pytest.mark.parametrize('status, fragment', [
    ('zaladowana', u'najpierw cofnij załadunek'),
    ('w_trasie', u'gdy kierowca rozliczy przystanek'),
])
def test_pinezka_zamowienia_z_trasy_zaladowanej_i_w_trasie_409(app, status, fragment):
    """Ręczna korekta i reset pinezki (geocoding → sprawdz_trase_przed_zmiana) blokuje ta sama bramka co adres."""
    order, _ = zamowienie_z_paczkami(statusy=('spakowane', 'spakowane'), zweryfikowane=False)
    t = trasa([order], status=status)
    for wywolanie in (lambda: geocoding.ustaw_recznie(order, 50.06, 19.94), lambda: geocoding.resetuj(order)):
        with pytest.raises(LogistykaBlad) as e:
            wywolanie()
        assert e.value.status == 409
        assert t.name in e.value.komunikat and fragment in e.value.komunikat
    assert OrderGeo.query.get(order.id) is None


@pytest.mark.parametrize('status, napis', [('zaladowana', u'załadowana'), ('w_trasie', u'w trasie')])
def test_edycja_trasy_zaladowanej_i_w_trasie_zablokowana(app, status, napis):
    t = trasa([], status=status)
    with pytest.raises(LogistykaBlad) as e:
        routes.edytuj(t, {'name': 'Inna', 'date_from': '2026-10-01'})
    assert e.value.status == 409 and napis in e.value.komunikat


@pytest.mark.parametrize('status', ['zaladowana', 'w_trasie'])
def test_zaladowana_i_w_trasie_zajmuja_pojazd_i_kierowce(app, status):
    v, k = pojazd(), kierowca()
    trasa([], status=status, vehicle_id=v.id, kierowca_id=k.id)
    z = routes.zajetosc(DZIEN, DZIEN)
    assert v.id in z['pojazdy'] and k.id in z['kierowcy']


def test_tablet_widzi_trase_zaladowana_i_w_trasie(app):
    a, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    b, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    ta, tb = trasa([a], status='zaladowana'), trasa([b], status='w_trasie')
    assert routes.trasa_dla_tabletu(a.id).id == ta.id
    assert routes.trasa_dla_tabletu(b.id).id == tb.id


@pytest.mark.parametrize('status, kod', [('robocza', 409), ('zatwierdzona', 200), ('zaladowana', 200),
                                         ('w_trasie', 200), ('wykonana', 200)])
def test_routimo_od_zatwierdzonej_wzwyz(app, client, status, kod):
    order, _ = zamowienie_z_paczkami()
    t = trasa([order], status=status)
    assert client.get(BASE + '/routes/%d/routimo' % t.id).status_code == kod


def test_lista_tras_sortuje_sekcje_po_cyklu(app, client):
    ids = {status: trasa([], status=status).id
           for status in ('wykonana', 'w_trasie', 'zaladowana', 'zatwierdzona', 'robocza')}
    r = client.get(BASE + '/routes')
    assert r.status_code == 200, r.get_data()[:300]
    assert [t['id'] for t in r.get_json()['routes']] == [ids['robocza'], ids['zatwierdzona'], ids['zaladowana'],
                                                         ids['w_trasie'], ids['wykonana']]


def test_cofniecie_weryfikacji_czysci_zaladunek(app):
    """Review Focus 2: weryfikator cofa weryfikację w trakcie załadunku (paczki już na aucie, trasa jeszcze
    zatwierdzona) — znaczniki załadunku znikają razem ze znacznikami weryfikacji."""
    order, lista_paczek = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    weryfikacja.cofnij_weryfikacje(order, worker_id=3, teraz=T0)
    db.session.commit()
    for p in lista_paczek:
        assert _bez_zaladunku(p)
        assert p.verified_at is None
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']


def test_regula_uniewaznienia_czysci_zaladunek(app):
    """Doróbka po załadunku (spec 4.5): pozycje załadowane wracają do „spakowane”, paczki unieważnione razem ze
    znacznikami załadunku, zamówienie zostaje na trasie (kierowca zobaczy NIESPAKOWANE)."""
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana')
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    order.products[0].current_status = 'czeka_na_wyciecie'       # doróbka
    db.session.commit()
    assert weryfikacja.uniewaznij_etapy(order, T0, u'doróbka') is True
    db.session.commit()
    assert [p.current_status for p in order.products] == ['czeka_na_wyciecie', 'spakowane']
    for p in lista_paczek:
        assert p.voided_at is not None and _bez_zaladunku(p)
    assert routes.przystanek_zamowienia(order.id).route_id == t.id


def test_deklaracja_odmawia_zamowieniu_zaladowanemu(app):
    """Uwaga z Ruling 27 kroku 4.3: deklaracja paczek odmawia także zamówieniu załadowanemu (409 order_verified)."""
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane',), numer_wewnetrzny='4401')
    with pytest.raises(paczki.PaczkiBlad) as e:
        paczki.zadeklaruj(order, paczki.Deklaracja('paczka', 1), 'packaging', {'type': 'device', 'id': 'TAB-1'},
                          teraz=T0)
    assert e.value.kod == 'order_verified' and u'załadowane' in e.value.komunikat


def test_etap_w_trasie_na_liscie_logistyki(app):
    jedzie, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    stoi, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    tj, ts = trasa([jedzie], status='w_trasie'), trasa([stoi], status='zaladowana')
    assert lista.serializuj(jedzie, None, tj)['etap'] == {'status': 'w_trasie', 'nazwa': 'W trasie'}
    assert lista.serializuj(stoi, None, ts)['etap'] == {'status': 'zaladowane', 'nazwa': u'Załadowane'}


def test_pobierz_filtruje_etap_w_trasie_i_zaladowane(app):
    """Etap „w_trasie” zastępuje „zaladowane” zamówieniu na trasie w drodze; filtr `etap` działa na etapie
    wiersza, więc `etap=zaladowane` takiego zamówienia nie zwraca."""
    jedzie, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    stoi, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    trasa([jedzie], status='w_trasie')
    trasa([stoi], status='zaladowana')
    numery = lambda etap: {w['numer'] for w in lista.pobierz(etap=etap)}
    assert numery('w_trasie') == {jedzie.internal_order_number}
    assert numery('zaladowane') == {stoi.internal_order_number}


def test_paczki_na_liscie_licza_zaladowane(app):
    order, lista_paczek = zamowienie_z_paczkami(paczek=3)
    t = trasa([order])
    zaladuj_wprost(lista_paczek[:2], t)
    assert lista.serializuj(order, None, t)['paczki'] == {'opis': u'3 × paczka', 'liczba': 3,
                                                          'zweryfikowane': 3, 'zaladowane': 2}


def test_paczki_na_liscie_licza_zaladunek_tylko_z_trasy_zamowienia(app):
    """Znacznik z innej trasy zostaje np. po „Cofnij zatwierdzenie” w trakcie załadunku i zmianie trasy —
    nie liczy się zamówieniu, a bez trasy zamówienia licznik to 0."""
    order, lista_paczek = zamowienie_z_paczkami(paczek=3)
    t, inna = trasa([order]), trasa([])
    zaladuj_wprost(lista_paczek[:2], inna)
    assert lista.serializuj(order, None, t)['paczki']['zaladowane'] == 0
    zaladuj_wprost(lista_paczek[2:], t)
    assert lista.serializuj(order, None, t)['paczki']['zaladowane'] == 1
    assert lista.serializuj(order, None, None)['paczki']['zaladowane'] == 0


def test_wyczysc_zaladunek_zwraca_liczbe_zaladowanych_paczek(app):
    order, lista_paczek = zamowienie_z_paczkami(paczek=3)
    zaladuj_wprost(lista_paczek[:2], trasa([order]), kto_id=7)
    assert paczki.wyczysc_zaladunek(lista_paczek) == 2
    assert all(_bez_zaladunku(p) for p in lista_paczek)
    assert paczki.wyczysc_zaladunek(lista_paczek) == 0


def test_znaczniki_base_dostawy(app):
    order, _ = zamowienie_z_paczkami()
    for funkcja, status in ((bl_sync.oznacz_zaladowane, 524520), (bl_sync.oznacz_wyslane, 149763),
                            (bl_sync.oznacz_dostarczone, 149778), (bl_sync.oznacz_planowana_trasa, 417343)):
        funkcja(order)
        assert order.bl_status_pending_id == status


def test_raporty_znaja_statusy_dostawy(app):
    """Spec 9.3: zamówienia na trasie i załadowane zostają w „Wyprodukowane”, a nazwy nie są „Status N”."""
    from modules.reports.models import BaselinkerReportOrder
    from modules.reports.service import STATUSY_BASELINKER
    assert STATUSY_BASELINKER[417343] == 'Planowana trasa'
    assert STATUSY_BASELINKER[524520] == u'Załadowane - trans. WoodPower'
    for status_id, nazwa in ((417343, 'Planowana trasa'), (524520, u'Załadowane - trans. WoodPower')):
        wiersz = BaselinkerReportOrder(current_status=nazwa, baselinker_status_id=status_id,
                                       total_volume=1.5, value_net=100)
        wiersz.update_production_fields()
        assert (wiersz.ready_pickup_volume, wiersz.ready_pickup_value_net) == (1.5, 100.0), status_id
        bez_id = BaselinkerReportOrder(current_status=nazwa, total_volume=2.0, value_net=50)
        bez_id.update_production_fields()
        assert bez_id.ready_pickup_volume == 2.0, nazwa
    with open(os.path.join(KORZEN, 'modules', 'baselinker', 'routers.py'), encoding='utf-8') as f:
        zrodlo = f.read()
    assert "417343: 'Planowana trasa'" in zrodlo and u"524520: 'Załadowane - trans. WoodPower'" in zrodlo


def test_cofniecie_sprawdzenia_paczki_czysci_zaladunek_zamowienia(app):
    """Weryfikator cofa sprawdzenie jednej paczki w trakcie załadunku — zamówienie wraca do „spakowane”, a znaczniki
    załadunku znikają ze wszystkich jego paczek (pozostałe paczki zostają sprawdzone)."""
    order, lista_paczek = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    wynik = weryfikacja.cofnij_sprawdzenie_paczki(lista_paczek[0], order, worker_id=3, teraz=T0)
    db.session.commit()
    assert wynik == (True, True)
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']
    assert all(_bez_zaladunku(p) for p in lista_paczek)
    assert lista_paczek[0].verified_at is None          # cofnięta paczka znowu niesprawdzona
    assert lista_paczek[1].verified_at is not None      # pozostałe zostają sprawdzone


def test_cofniecie_sprawdzenia_paczki_zamowienia_zaladowanego_409(app):
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana')
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    with pytest.raises(weryfikacja.WeryfikacjaBlad) as e:
        weryfikacja.cofnij_sprawdzenie_paczki(lista_paczek[0], order, worker_id=3, teraz=T0)
    assert e.value.kod == 'order_status'
    db.session.rollback()
    # Odmowa niczego nie zmieniła: znaczniki załadunku i weryfikacji stoją jak przed wywołaniem.
    assert all((p.loaded_at, p.loaded_by_worker_id, p.loaded_method, p.loaded_route_id) == (T0, 7, 'skan', t.id)
               and p.verified_at is not None for p in lista_paczek)
