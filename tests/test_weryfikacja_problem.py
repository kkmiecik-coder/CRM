# -*- coding: utf-8 -*-
"""Problem przy weryfikacji, „Cofnij do pakowania” i baner repack_reason na tablecie pakowania
(logistyka etap 4, krok 4.3, spec 4.5, 8.3 i 8.4)."""
import itertools
from datetime import date, datetime, timedelta

import pytest
from flask import g, jsonify

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog, Route, RouteStop
from modules.production.logistics.routers import weryfikacja_api
from modules.production.logistics.services import bl_sync, weryfikacja
from modules.production.models import (ProcessedMobileOperation, ProductionConfig, ProductionDevice,
                                       ProductionOrder, ProductionPackage, get_local_now)
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, pracownik, zamowienie  # noqa: F401
from tests.weryfikacja_pomocnicze import migawka_pozycji

BASE = '/api/mobile/verification'
T0 = datetime(2026, 10, 1, 8, 0)
_licznik = itertools.count(1)
_numery = itertools.count(3100)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


@pytest.fixture()
def dopychacz(app, monkeypatch):
    wolania = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app: wolania.append('start') or True)
    # `g` jest w testach wspólny dla żądań (testowy klient wchodzi w app_context fixtury) — lista
    # „do wysłania po commicie” nie może przeciekać między testami ani między żądaniami.
    g.pop('_logistyka_bl_po_commicie', None)
    yield wolania
    g.pop('_logistyka_bl_po_commicie', None)


def _urzadzenie(stanowisko='verification'):
    device = ProductionDevice(device_id='TEL-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Telefon', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, kto=None, op_id=None):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device),
                'X-Operation-Id': op_id or 'op-prob-%d' % next(_licznik)}
    if kto is not None:
        naglowki['X-Worker-Ids'] = str(kto.id)
    return naglowki


def _z_paczkami(statusy=('spakowane', 'spakowane'), n=2, sposob=s.KURIER, zweryfikowane=False,
                spakowano=None, **kolumny):
    order = zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)),
                       packages_declared_at=T0, **kolumny)
    # „Teraz”, nie stała data: zakres listy Weryfikacji (warunek_zakresu) liczy zamówienia zamknięte
    # w Logistyce od packaging_completed_at w oknie 7 dni — stała T0 wypadłaby z niego za tydzień.
    for p in order.products:
        p.packaging_completed_at = spakowano or get_local_now()
    db.session.add_all([ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0,
                                          verified_at=T0 if zweryfikowane else None,
                                          verified_method='skan' if zweryfikowane else None)
                        for i in range(1, n + 1)])
    db.session.commit()
    return order


def _post(client, order, akcja, device, kto, **body):
    return client.post('%s/orders/%s/%s' % (BASE, order.internal_order_number, akcja), json=body,
                       headers=_naglowki(device, kto))


def _akcje(order):
    return [w.action for w in LogisticsLog.query.filter_by(order_id=order.id).order_by(LogisticsLog.id)]


def test_problem_na_spakowanym(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    r = _post(client, order, 'problem', device, kto, reason='brak_elementu', note=u'  brak   nóżki ')
    assert r.status_code == 200, r.get_json()
    o = ProductionOrder.query.get(order.id)
    assert (o.problem_reason, o.problem_note, o.problem_by_worker_id) == ('brak_elementu', u'brak nóżki', kto.id)
    assert r.get_json()['order']['problem']['reason_label'] == u'Brak elementu'
    assert _akcje(order) == ['problem']


def test_problem_na_zweryfikowanym_cofa_weryfikacje(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0)
    assert _post(client, order, 'problem', device, kto, reason='uszkodzenie').status_code == 200
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane'] and o.verified_at is None
    assert all(p.verified_at is None for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert _akcje(order) == ['weryfikacja_cofnieta', 'problem']
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja_cofnieta').one().note == \
        u'problem: Uszkodzenie'


def test_ponowny_problem_nadpisuje(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    _post(client, order, 'problem', device, kto, reason='etykieta')
    _post(client, order, 'problem', device, kto, reason='opakowanie', note='x' * 300)
    o = ProductionOrder.query.get(order.id)
    assert o.problem_reason == 'opakowanie' and len(o.problem_note) == 255
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='problem').order_by(LogisticsLog.id.desc()).first()
    assert (wpis.old_value, wpis.new_value) == ('etykieta', 'opakowanie')


def test_zly_powod_422_zapamietany(app, client):
    r = _post(client, _z_paczkami(), 'problem', _urzadzenie(), pracownik(), reason='pogoda')
    assert (r.status_code, r.get_json()['error']) == (422, 'invalid_problem')
    assert ProcessedMobileOperation.query.count() == 1


@pytest.mark.parametrize('akcja', ['problem', 'revert-to-packing'])
def test_powod_innego_typu_niz_tekst_to_422_a_nie_500(app, client, akcja, dopychacz):
    """Lista w `reason` nie jest hashowalna (TypeError → 500 → telefon ponawia bez końca); ciało
    JSON niebędące obiektem też nie może wywalić endpointu."""
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    r = _post(client, order, akcja, device, kto, reason=['brak_elementu'])
    assert (r.status_code, r.get_json()['error']) == (422, 'invalid_problem')
    r = client.post('%s/orders/%s/%s' % (BASE, order.internal_order_number, akcja), json=['x'],
                    headers=_naglowki(device, kto))
    assert (r.status_code, r.get_json()['error']) == (422, 'invalid_problem')
    assert ProductionOrder.query.get(order.id).problem_at is None and dopychacz == []


@pytest.mark.parametrize('statusy, kod', [(('dostarczone',), 'order_status'),
                                          (('spakowane', 'czeka_na_pakowanie'), 'order_not_packed')])
def test_problem_odmowy(app, client, statusy, kod):
    r = _post(client, _z_paczkami(statusy=statusy), 'problem', _urzadzenie(), pracownik(), reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, kod)
    assert ProcessedMobileOperation.query.count() == 0           # 409 niezapamiętane (BLEDY_DO_PONOWIENIA)


def test_rozwiazanie_problemu(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(problem_reason='etykieta', problem_at=T0)
    r = _post(client, order, 'problem/resolve', device, kto)
    assert r.status_code == 200 and r.get_json()['changed'] is True
    o = ProductionOrder.query.get(order.id)
    assert (o.problem_reason, o.problem_note, o.problem_at, o.problem_by_worker_id) == (None, None, None, None)
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='problem_rozwiazany').one()
    assert (wpis.old_value, wpis.worker_id) == ('etykieta', kto.id)
    bez = _post(client, order, 'problem/resolve', device, kto)
    assert bez.status_code == 200 and bez.get_json()['changed'] is False


def test_cofniecie_do_pakowania(app, client, dopychacz):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0,
                        logistics_closed_at=T0)
    r = _post(client, order, 'revert-to-packing', device, kto, reason='brak_elementu', note=u'brak nóżki')
    assert r.status_code == 200, r.get_json()
    o = ProductionOrder.query.get(order.id)
    assert [(p.current_status, p.quantity_done_packaging, p.packaging_completed_at) for p in o.products] == \
        [('czeka_na_pakowanie', 0, None), ('czeka_na_pakowanie', 0, None)]
    assert (o.repack_required, o.repack_reason) == (True, u'Weryfikacja: Brak elementu: brak nóżki')
    assert (o.verified_at, o.packages_declared_at, o.logistics_closed_at) == (None, None, None)
    assert o.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
    assert all(p.voided_at is not None for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert 'cofniete_do_pakowania' in _akcje(order)
    assert dopychacz == ['start']                         # dopychacz Base. dopiero po commicie


def test_cofniecie_przenosi_problem_do_banera(app, client, dopychacz):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(problem_reason='uszkodzenie', problem_note=u'pęknięty blat', problem_at=T0)
    assert _post(client, order, 'revert-to-packing', device, kto).status_code == 200
    o = ProductionOrder.query.get(order.id)
    assert o.repack_reason == u'Weryfikacja: Uszkodzenie: pęknięty blat' and o.problem_at is None
    assert LogisticsLog.query.filter_by(order_id=order.id, action='problem_rozwiazany').one().note == \
        u'przeniesiony do banera pakowania'


def test_cofniecie_bez_powodu_i_bez_problemu_422(app, client, dopychacz):
    r = _post(client, _z_paczkami(), 'revert-to-packing', _urzadzenie(), pracownik())
    assert (r.status_code, r.get_json()['error']) == (422, 'invalid_problem')
    assert dopychacz == []


def test_zamowienie_na_trasie_zostaje_na_niej(app, client, dopychacz):
    order = _z_paczkami(sposob=s.TRANSPORT)
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 7), date_to=date(2026, 10, 7), status='zatwierdzona')
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    db.session.commit()
    assert _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne').status_code == 200
    assert RouteStop.query.filter_by(order_id=order.id).one().route_id == trasa.id


def test_baner_na_tablecie_i_ponowne_spakowanie(app, client, dopychacz):
    order = _z_paczkami()
    _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='opakowanie')
    tablet = _urzadzenie('packaging')
    r = client.get('/api/mobile/stations/packaging/orders', headers={'Authorization': 'Bearer ' + generate_token(tablet)})
    transport = r.get_json()['orders'][0]['transport']
    # Baner z Weryfikacji idzie w API tylko jako repack_reason; repack_required=true znaczy tam wyłącznie
    # „przepakuj na kuriera” (stara appka pokazałaby przy nim na sztywno „PRZEPAKUJ NA KURIERA”).
    assert (transport['repack_required'], transport['repack_reason']) == (False, u'Weryfikacja: Opakowanie')
    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI >= 5      # repack_reason wszedł w kształcie 5
    o = ProductionOrder.query.get(order.id)
    for p in o.products:
        p.complete_task('packaging')
    db.session.commit()
    o = ProductionOrder.query.get(order.id)
    assert (o.repack_required, o.repack_reason) == (False, None)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane']


def test_problem_na_zamowieniu_z_czescia_sprawdzonych_paczek(app, client):
    """Zamówienie jeszcze 'spakowane', ale jedna paczka już sprawdzona — problem czyści znacznik."""
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    ProductionPackage.query.filter_by(order_id=order.id, seq=1).one().verified_at = T0
    db.session.commit()
    assert _post(client, order, 'problem', device, kto, reason='etykieta').status_code == 200
    assert all(p.verified_at is None and p.verified_by_worker_id is None and p.verified_method is None
               for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert _akcje(order) == ['weryfikacja_cofnieta', 'problem']


def test_cofniecie_do_pakowania_przenosi_notatke_problemu_przy_podanym_powodzie(app, client, dopychacz):
    """M1: żądanie ma `reason`, ale nie `note` — notatka otwartego problemu też trafia do banera."""
    order = _z_paczkami(problem_reason='uszkodzenie', problem_note=u'pęknięty blat', problem_at=T0)
    r = _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='brak_elementu')
    assert r.status_code == 200, r.get_json()
    o = ProductionOrder.query.get(order.id)
    assert o.repack_reason == u'Weryfikacja: Brak elementu: pęknięty blat' and o.problem_at is None
    # notatka z żądania wygrywa z notatką problemu
    drugie = _z_paczkami(problem_reason='uszkodzenie', problem_note=u'pęknięty blat', problem_at=T0)
    _post(client, drugie, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne', note=u'do wymiany')
    assert ProductionOrder.query.get(drugie.id).repack_reason == u'Weryfikacja: Inne: do wymiany'


def test_cofniecie_409_nie_uruchamia_dopychacza_i_nie_jest_zapamietane(app, client, dopychacz):
    order = _z_paczkami(statusy=('spakowane', 'czeka_na_pakowanie'))
    r = _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, 'order_not_packed')
    assert dopychacz == [] and not g.get('_logistyka_bl_po_commicie')
    assert ProcessedMobileOperation.query.count() == 0


def test_powtorka_cofniecia_nie_uruchamia_dopychacza_drugi_raz(app, client, dopychacz):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    naglowki = _naglowki(device, kto, op_id='op-prob-powtorka')
    url = '%s/orders/%s/revert-to-packing' % (BASE, order.internal_order_number)
    pierwsze = client.post(url, json={'reason': 'inne'}, headers=naglowki)
    assert pierwsze.status_code == 200 and dopychacz == ['start']
    druga = client.post(url, json={'reason': 'inne'}, headers=naglowki)
    assert druga.get_json() == pierwsze.get_json()
    assert dopychacz == ['start']                               # powtórka idempotentna nie startuje drugi raz
    assert LogisticsLog.query.filter_by(order_id=order.id, action='cofniete_do_pakowania').count() == 1


def test_rollback_po_zaplanowaniu_nie_uruchamia_dopychacza(app, client, dopychacz, monkeypatch):
    """Handler zdążył zaplanować dopychacz, ale odpowiedź jest 409 (rollback) — nic nie startuje."""
    monkeypatch.setattr(weryfikacja_api, '_odpowiedz',
                        lambda *a, **k: (jsonify({'error': 'test', 'message': 'x'}), 409))
    order = _z_paczkami()
    r = _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne')
    assert r.status_code == 409
    assert dopychacz == []
    assert not ProductionOrder.query.get(order.id).repack_required      # zapis cofnięty


# --- Zapisy decydują na bieżącym stanie pozycji (migawka MySQL odtworzona przelotką) ---------------

def test_problem_po_cichym_przepakowaniu_to_409(app, client, monkeypatch):
    order = _z_paczkami()
    migawka_pozycji(monkeypatch, weryfikacja, 'zglos_problem', w_pamieci='spakowane', w_bazie='czeka_na_pakowanie')
    r = _post(client, order, 'problem', _urzadzenie(), pracownik(), reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, 'order_not_packed')


def test_problem_cofa_weryfikacje_na_biezacych_statusach(app, client, monkeypatch):
    """Pozycje w pamięci 'spakowane', w bazie już 'zweryfikowane': decyzja o cofnięciu i przestawienie
    pozycji idą na bieżącym stanie — inaczej weryfikacja zamówienia znika, a pozycje zostają zweryfikowane."""
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0)
    migawka_pozycji(monkeypatch, weryfikacja, 'zglos_problem', w_pamieci='spakowane')
    assert _post(client, order, 'problem', device, kto, reason='uszkodzenie').status_code == 200
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane'] and o.verified_at is None
    assert _akcje(order) == ['weryfikacja_cofnieta', 'problem']


def test_cofniecie_do_pakowania_po_cichym_wydaniu_to_409(app, client, dopychacz, monkeypatch):
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0)
    migawka_pozycji(monkeypatch, weryfikacja, 'cofnij_do_pakowania',
                    w_pamieci='zweryfikowane', w_bazie='dostarczone')
    r = _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, 'order_status')
    assert dopychacz == []


def test_cofniecie_do_pakowania_przestawia_pozycje_z_biezacego_stanu(app, client, dopychacz, monkeypatch):
    """Pozycje przestawione 'w tle' z 'zweryfikowane' na 'spakowane' też wracają do czeka_na_pakowanie,
    a licznik pakowania zeruje się od bieżącej wartości."""
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0)
    for p in order.products:
        p.quantity_done_packaging = p.quantity
    db.session.commit()
    migawka_pozycji(monkeypatch, weryfikacja, 'cofnij_do_pakowania', w_pamieci='zweryfikowane', w_bazie='spakowane')
    assert _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne').status_code == 200
    o = ProductionOrder.query.get(order.id)
    assert [(p.current_status, p.quantity_done_packaging) for p in o.products] == \
        [('czeka_na_pakowanie', 0), ('czeka_na_pakowanie', 0)]


# --- Zapisy tylko w zakresie listy (fala końcowa 4.3, F2) ---------------------------------------------
# Zakres = zamówienie otwarte w Logistyce albo z pozycją spakowaną od początku okna (7 dni, nie wcześniej
# niż wdrożenie) ALBO z otwartym problemem. Poza nim każdy zapis poza problem/resolve: 409 order_status,
# niezapamiętane, bez dopychacza Base. Zamówienie kurierskie po weryfikacji jest zamknięte w Logistyce,
# więc o zakresie decyduje data spakowania.

def _stary_kurier(statusy=('spakowane', 'spakowane'), dni=10, **kolumny):
    """Zamówienie kurierskie zamknięte w Logistyce, spakowane `dni` dni temu (okno listy to 7)."""
    dawno = get_local_now() - timedelta(days=dni)
    return _z_paczkami(statusy=statusy, spakowano=dawno, logistics_closed_at=dawno,
                       zweryfikowane=statusy[0] == 'zweryfikowane', **kolumny)


def _stan(order):
    """Stan zamówienia z bazy (po wygaszeniu sesji) — do porównania „przed” i „po” odmowie."""
    db.session.expire_all()
    o = ProductionOrder.query.get(order.id)
    return ([p.current_status for p in o.products], o.verified_at, o.problem_at, o.problem_reason,
            o.repack_required, o.repack_reason, o.packages_declared_at, o.logistics_closed_at,
            o.bl_status_pending_id,
            [(x.verified_at, x.voided_at) for x in ProductionPackage.query.filter_by(order_id=order.id)
             .order_by(ProductionPackage.seq)])


def _wywolaj(client, order, akcja, device, kto):
    if akcja == 'verify':
        paczka = ProductionPackage.query.filter_by(order_id=order.id, seq=1).one()
        return client.post('%s/packages/%d/verify' % (BASE, paczka.id), json={'method': 'skan'},
                           headers=_naglowki(device, kto))
    return _post(client, order, akcja, device, kto, reason='inne')


@pytest.mark.parametrize('akcja', ['verify', 'verify-all', 'unverify', 'problem', 'revert-to-packing'])
def test_zapis_poza_zakresem_listy_to_409_order_status(app, client, dopychacz, akcja):
    kto, device = pracownik(), _urzadzenie()
    zweryfikowane = akcja == 'unverify'       # cofnięcie weryfikacji ma sens dopiero na zweryfikowanym
    order = _stary_kurier(statusy=('zweryfikowane',) * 2 if zweryfikowane else ('spakowane',) * 2,
                          verified_at=T0 if zweryfikowane else None)
    przed = _stan(order)
    r = _wywolaj(client, order, akcja, device, kto)
    assert (r.status_code, r.get_json()['error']) == (409, 'order_status'), r.get_json()
    assert u'poza listą Weryfikacji' in r.get_json()['message']
    assert order.internal_order_number in r.get_json()['message']
    assert _stan(order) == przed                                  # nic się nie zmieniło
    assert ProcessedMobileOperation.query.count() == 0            # 409 niezapamiętane (BLEDY_DO_PONOWIENIA)
    assert _akcje(order) == []
    assert dopychacz == [] and not g.get('_logistyka_bl_po_commicie')   # dopychacz Base. nie wystartował


def test_odmowa_poza_zakresem_nie_otwiera_zamowienia_i_nie_wysyla_138620(app, client, dopychacz):
    """Sedno poprawki: „Cofnij do pakowania” na starym zamówieniu kurierskim nie otwiera go w Logistyce."""
    order = _stary_kurier(statusy=('zweryfikowane', 'zweryfikowane'), verified_at=T0)
    r = _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='uszkodzenie')
    assert r.status_code == 409
    o = ProductionOrder.query.get(order.id)
    assert (o.repack_required, o.bl_status_pending_id) == (False, None) and o.logistics_closed_at is not None
    assert all(p.voided_at is None for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert dopychacz == []


def test_poza_zakresem_z_otwartym_problemem_mozna_rozwiazac_i_cofnac_do_pakowania(app, client, dopychacz):
    """Otwarty problem = w zakresie: `problem/resolve` działa, `revert-to-packing` też (i uruchamia dopychacz)."""
    kto, device = pracownik(), _urzadzenie()
    do_rozwiazania = _stary_kurier(problem_reason='etykieta', problem_at=T0)
    r = _post(client, do_rozwiazania, 'problem/resolve', device, kto)
    assert r.status_code == 200 and r.get_json()['changed'] is True
    assert ProductionOrder.query.get(do_rozwiazania.id).problem_at is None
    # po rozwiązaniu problemu zamówienie wraca poza zakres, więc kolejny zapis jest już odrzucony
    po = _post(client, do_rozwiazania, 'problem', device, kto, reason='inne')
    assert (po.status_code, po.get_json()['error']) == (409, 'order_status')

    do_cofniecia = _stary_kurier(problem_reason='uszkodzenie', problem_note=u'pęknięty blat', problem_at=T0)
    r = _post(client, do_cofniecia, 'revert-to-packing', device, kto)
    assert r.status_code == 200, r.get_json()
    o = ProductionOrder.query.get(do_cofniecia.id)
    assert o.repack_reason == u'Weryfikacja: Uszkodzenie: pęknięty blat' and o.logistics_closed_at is None
    assert dopychacz == ['start']


def test_poza_zakresem_z_otwartym_problemem_problem_open_wygrywa_z_zakresem(app, client):
    """Kolejność sprawdzeń: bardziej konkretny kod (problem_open) przed zakresem; sam problem w zakresie."""
    kto, device = pracownik(), _urzadzenie()
    order = _stary_kurier(problem_reason='inne', problem_at=T0)
    r = _wywolaj(client, order, 'verify', device, kto)
    assert (r.status_code, r.get_json()['error']) == (409, 'problem_open')
    ponowne = _post(client, order, 'problem', device, kto, reason='etykieta')      # nadpisanie powodu działa
    assert ponowne.status_code == 200
    assert ProductionOrder.query.get(order.id).problem_reason == 'etykieta'


@pytest.mark.parametrize('statusy, kod, fragment', [
    (('spakowane', 'czeka_na_pakowanie'), 'order_not_packed', u'nie jest jeszcze w całości spakowane'),
    (('dostarczone', 'dostarczone'), 'order_status', u'już dostarczone'),
    (('zaladowane', 'zaladowane'), 'order_status', u'już załadowane'),
])
def test_poza_zakresem_konkretniejsze_sprawdzenie_stanu_wygrywa_z_zakresem(app, client, statusy, kod, fragment):
    r = _post(client, _stary_kurier(statusy=statusy), 'problem', _urzadzenie(), pracownik(), reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, kod)
    assert fragment in r.get_json()['message'] and u'poza listą' not in r.get_json()['message']


def test_zamowienie_spakowane_przed_wdrozeniem_weryfikacji_jest_poza_zakresem(app, client, dopychacz):
    teraz = get_local_now()
    db.session.add(ProductionConfig(config_key='logistyka_weryfikacja_od', config_type='string',
                                    config_value=(teraz - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')))
    db.session.commit()
    kto, device = pracownik(), _urzadzenie()
    # 3 dni temu: w oknie 7 dni, ale PRZED wdrożeniem kroku 4.3 — poza zakresem
    przed = teraz - timedelta(days=3)
    stare = _z_paczkami(spakowano=przed, logistics_closed_at=przed)
    r = _post(client, stare, 'revert-to-packing', device, kto, reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, 'order_status')
    assert dopychacz == [] and ProductionOrder.query.get(stare.id).logistics_closed_at is not None
    # spakowane po wdrożeniu, choć też zamknięte w Logistyce: w zakresie
    po = _z_paczkami(spakowano=teraz - timedelta(hours=2), logistics_closed_at=teraz - timedelta(hours=2))
    assert _post(client, po, 'problem', device, kto, reason='inne').status_code == 200


def test_zamkniete_spakowane_wczoraj_i_otwarte_bez_wzgledu_na_date_sa_w_zakresie(app, client):
    kto, device = pracownik(), _urzadzenie()
    wczoraj = _stary_kurier(dni=1)
    assert _post(client, wczoraj, 'problem', device, kto, reason='inne').status_code == 200
    otwarte = _stary_kurier(dni=30)
    ProductionOrder.query.get(otwarte.id).logistics_closed_at = None       # otwarte w Logistyce: bez względu na datę
    db.session.commit()
    assert _post(client, otwarte, 'problem', device, kto, reason='inne').status_code == 200


def test_odczyt_zamowienia_poza_zakresem_zostaje_bez_ograniczenia(app, client):
    order = _stary_kurier()
    r = client.get('%s/orders/%s' % (BASE, order.internal_order_number), headers=_naglowki(_urzadzenie()))
    assert r.status_code == 200 and r.get_json()['order']['internal_order_number'] == order.internal_order_number


# --- Zakres sprawdzany dopiero przed faktycznym zapisem (fala końcowa 4.3, F12) -------------------------

def test_ponowny_skan_sprawdzonej_paczki_poza_zakresem_to_200_bez_zmian(app, client, dopychacz):
    """Skan, który niczego nie zapisuje, nie sprawdza zakresu: stare zamówienie kurierskie (zweryfikowane,
    paczki sprawdzone) daje 200 `changed: false`, jak przed F2."""
    kto, device = pracownik(), _urzadzenie()
    order = _stary_kurier(statusy=('zweryfikowane', 'zweryfikowane'), verified_at=T0)
    przed = _stan(order)
    r = _wywolaj(client, order, 'verify', device, kto)
    assert r.status_code == 200, r.get_json()
    assert (r.get_json()['changed'], r.get_json()['order_verified']) == (False, True)
    assert _stan(order) == przed and _akcje(order) == [] and dopychacz == []


def test_zweryfikuj_wszystkie_na_juz_zweryfikowanym_poza_zakresem_to_200_bez_zmian(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _stary_kurier(statusy=('zweryfikowane', 'zweryfikowane'), verified_at=T0)
    przed = _stan(order)
    r = _post(client, order, 'verify-all', device, kto)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['changed'] is False
    assert _stan(order) == przed and _akcje(order) == []


def test_skan_pierwszej_niesprawdzonej_paczki_poza_zakresem_to_409(app, client):
    """Pierwszy skan zapisuje, więc zakres obowiązuje (to samo co w parametryzowanym teście `verify`,
    tu z drugą paczką już sprawdzoną: zmiana nadal jest zapisem)."""
    kto, device = pracownik(), _urzadzenie()
    order = _stary_kurier()
    ProductionPackage.query.filter_by(order_id=order.id, seq=2).one().verified_at = T0
    db.session.commit()
    przed = _stan(order)
    r = _wywolaj(client, order, 'verify', device, kto)
    assert (r.status_code, r.get_json()['error']) == (409, 'order_status')
    assert _stan(order) == przed and ProcessedMobileOperation.query.count() == 0


def test_domkniecie_z_f3_poza_zakresem_to_409(app, client):
    """Skan sprawdzonej paczki, który domknąłby zamówienie (F3), jest zapisem, więc poza zakresem 409."""
    kto, device = pracownik(), _urzadzenie()
    order = _stary_kurier()
    for p in ProductionPackage.query.filter_by(order_id=order.id):
        p.verified_at, p.verified_method = T0, 'skan'
    db.session.commit()
    przed = _stan(order)
    r = _wywolaj(client, order, 'verify', device, kto)
    assert (r.status_code, r.get_json()['error']) == (409, 'order_status')
    assert _stan(order) == przed and _akcje(order) == []
