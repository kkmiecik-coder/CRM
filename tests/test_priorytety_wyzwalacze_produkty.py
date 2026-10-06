# -*- coding: utf-8 -*-
"""
Wyzwalacze `kolejka.utrwal()` w panelu produktów (plan K1, Task 6; spec 2026-10-04, sekcja 9.3): hurtowa zmiana
statusu i zmiany z Base. — po commicie zapisu. Hurtową zmianę PRIORYTETU usunął krok K2 (400, bez przeliczenia).

Osobny plik od tests/test_priorytety_wyzwalacze.py: tamte testy stoją na aplikacji logistyki, te na aplikacji API
produkcji (krawedzie_fixtures), a obie fikstury nazywają się `app`.
Plik nie zakłada tabeli prod_product_events (konwencja pakietu).
"""
from datetime import date

import pytest

from extensions import db
from modules.production.models import ProductionOrder, ProductionProduct
from modules.production.services.sync_service import BaselinkerSyncService
from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401
from tests.priorytety_fixtures import (  # noqa: F401
    czyste_ustawienia, drabina_domyslna, szpieg_utrwal, zamrozony_dzien)

pytestmark = pytest.mark.usefixtures('zamrozony_dzien', 'czyste_ustawienia')


def _masowo(client, akcja, ids, **parametry):
    return client.post(BASE + '/products/bulk-action', json={
        'action': akcja, 'product_ids': ids, 'parameters': parametry})


def _ranga_pozycji(pid):
    db.session.rollback()
    db.session.expire_all()
    return db.session.get(ProductionProduct, pid).priority_rank


def test_hurt_statusu_utrwala_a_update_priority_odrzucone(app, client, szpieg_utrwal):
    with app.app_context():
        drabina_domyslna()
    pilna, _ = produkt(app, status='czeka_na_sklejanie', numer='25/00001', deadline_date=date(2026, 10, 30))
    pozna, _ = produkt(app, status='czeka_na_sklejanie', numer='25/00002', deadline_date=date(2026, 11, 20))

    # hurtowa zmiana statusu: wstrzymanie zabiera zamówienie z kolejki → przeliczenie po commicie
    r = _masowo(client, 'update_status', [pilna], new_status='wstrzymane')
    assert r.status_code == 200, r.get_data()[:300]
    assert len(szpieg_utrwal) == 1
    assert szpieg_utrwal[0]['czysta'] is True and szpieg_utrwal[0]['zrodlo'] is None
    with app.app_context():
        assert db.session.get(ProductionProduct, pilna).current_status == 'wstrzymane'
        assert _ranga_pozycji(pozna) == 101                      # jedyne aktywne zamówienie: ranga 1
        zamowienie_pozne = db.session.get(ProductionProduct, pozna).order_id
        assert db.session.get(ProductionOrder, zamowienie_pozne).priority_rank == 1

    # hurtowa zmiana priorytetu usunięta w K2: 400, ranga bez zmian, bez przeliczenia
    r = _masowo(client, 'update_priority', [pozna], new_priority=42)
    assert r.status_code == 400, r.get_data()[:300]
    assert len(szpieg_utrwal) == 1
    with app.app_context():
        assert _ranga_pozycji(pozna) == 101

    # odmowa (nieznany status) — bez przeliczenia
    assert _masowo(client, 'update_status', [pozna], new_status='czeka_na_wykanczanie').status_code == 400
    assert len(szpieg_utrwal) == 1


def test_zmiany_z_base_utrwalaja(app, client, szpieg_utrwal, monkeypatch):
    """Base. podmienione: serwis zmian zapisuje i commituje sam, końcówka przelicza rangi po jego sukcesie."""
    with app.app_context():
        drabina_domyslna()
    pid, _ = produkt(app, status='czeka_na_sklejanie', numer='25/00001', deadline_date=date(2026, 10, 30))
    wyniki = [{'success': True, 'message': 'ok'}, {'success': False, 'error': 'odmowa Base.'}]

    def zmiany(self, baselinker_order_id, changes, user_id=None):
        wynik = wyniki.pop(0)
        if wynik['success']:
            db.session.get(ProductionProduct, pid).quantity = 7        # zapis serwisu, zatwierdzony przez serwis
            db.session.commit()
        return wynik

    monkeypatch.setattr(BaselinkerSyncService, 'apply_baselinker_changes', zmiany)
    cialo = {'baselinker_order_id': 2500001, 'changes': {'products_to_add': [], 'products_to_remove': [],
                                                        'products_to_update': [{'id': pid}]}}

    r = client.post(BASE + '/admin/apply-baselinker-changes', json=cialo)
    assert r.status_code == 200 and r.get_json()['success'] is True
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True and szpieg_utrwal[0]['zrodlo'] is None
    with app.app_context():
        assert _ranga_pozycji(pid) == 101

    # serwis odmówił — nic się nie zmieniło, nie przeliczamy
    r = client.post(BASE + '/admin/apply-baselinker-changes', json=cialo)
    assert r.get_json()['success'] is False
    assert len(szpieg_utrwal) == 1


# ── Sygnały dla tabletów po commicie (krok K3; spec 5.4) ────────────────────────────────────────────────────

@pytest.fixture()
def wyslane_sygnaly(app, monkeypatch):
    """Kanały, na które poszła publikacja realtime, w kolejności; ('COMMIT') przy każdym commicie połączenia."""
    from sqlalchemy import event
    from modules.production.services import realtime_service
    zdarzenia = []
    monkeypatch.setattr(realtime_service, 'publish', lambda kanal, dane: zdarzenia.append(kanal) or True)

    def po_commicie(_polaczenie):
        zdarzenia.append('COMMIT')

    with app.app_context():
        event.listen(db.engine, 'commit', po_commicie)
    yield zdarzenia
    with app.app_context():
        event.remove(db.engine, 'commit', po_commicie)


def _kafel_pozycji(app, stanowisko, pid):
    from datetime import datetime
    from modules.production.priorytety.models import StationDesk
    with app.app_context():
        pozycja = db.session.get(ProductionProduct, pid)
        db.session.add(StationDesk(station_code=stanowisko, order_id=pozycja.order_id, product_id=pid,
                                   unit_key='p:%d' % pid, pulled_at=datetime(2026, 10, 5, 8, 0), zrodlo='kolejka'))
        db.session.commit()


def test_hurt_sygnal_na_zdjete_i_docelowe(app, client, wyslane_sygnaly, monkeypatch):
    """Hurtowa zmiana statusu: sygnał na stanowisko, z którego zdjęto kafel, i na stanowisko docelowe nowego
    statusu — po commicie zapisu. Wstrzymanie nie ma stanowiska docelowego."""
    from modules.production.priorytety.models import StationDesk
    from modules.production.priorytety.services import kolejka
    monkeypatch.setattr(kolejka, 'utrwal', lambda *a, **k: {'success': True})
    przesuwana, _ = produkt(app, status='czeka_na_sklejanie', numer='25/00001')
    wstrzymywana, _ = produkt(app, status='czeka_na_sklejanie', numer='25/00002')
    bez_kafla, _ = produkt(app, status='czeka_na_krawedzie', numer='25/00003')
    _kafel_pozycji(app, 'gluing', przesuwana)
    _kafel_pozycji(app, 'gluing', wstrzymywana)

    del wyslane_sygnaly[:]
    r = _masowo(client, 'update_status', [przesuwana], new_status='czeka_na_formatowanie')
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['zdjete_stanowiska'] == ['gluing']
    kanaly = [z for z in wyslane_sygnaly if z != 'COMMIT']
    assert kanaly == ['station:gluing', 'station:formatting']
    assert 'COMMIT' in wyslane_sygnaly[:wyslane_sygnaly.index('station:gluing')]

    del wyslane_sygnaly[:]
    assert _masowo(client, 'update_status', [wstrzymywana], new_status='wstrzymane').status_code == 200
    assert [z for z in wyslane_sygnaly if z != 'COMMIT'] == ['station:gluing']

    # pozycja bez kafla: sygnał tylko na stanowisko docelowe
    del wyslane_sygnaly[:]
    assert _masowo(client, 'update_status', [bez_kafla], new_status='czeka_na_pakowanie').status_code == 200
    assert [z for z in wyslane_sygnaly if z != 'COMMIT'] == ['station:packaging']
    with app.app_context():
        assert StationDesk.query.count() == 0

    # odmowa (nieznany status) — bez sygnału
    del wyslane_sygnaly[:]
    assert _masowo(client, 'update_status', [bez_kafla], new_status='czeka_na_wykanczanie').status_code == 400
    assert [z for z in wyslane_sygnaly if z != 'COMMIT'] == []


def test_base_sygnal_po_wyniku(app, client, wyslane_sygnaly, monkeypatch):
    """Zmiany z Base.: końcówka wysyła sygnały PO wyniku serwisu (serwis commituje sam) — stanowiskom, z których
    zdjęto kafel, i Wycinaniu, gdy doszła nowa pozycja. Odmowa serwisu — bez sygnału."""
    from modules.production.priorytety.services import kolejka
    monkeypatch.setattr(kolejka, 'utrwal', lambda *a, **k: {'success': True})
    wyniki = [{'success': True, 'added': 1, 'removed': 1, 'zdjete_stanowiska': ['packaging', 'gluing']},
              {'success': True, 'added': 0, 'removed': 0, 'zdjete_stanowiska': []},
              {'success': False, 'error': 'odmowa Base.', 'added': 1, 'zdjete_stanowiska': ['gluing']}]

    def zmiany(self, baselinker_order_id, changes, user_id=None):
        db.session.commit()
        return wyniki.pop(0)

    monkeypatch.setattr(BaselinkerSyncService, 'apply_baselinker_changes', zmiany)
    cialo = {'baselinker_order_id': 2500001, 'changes': {'products_to_add': [{'order_product_id': '1'}]}}

    del wyslane_sygnaly[:]
    assert client.post(BASE + '/admin/apply-baselinker-changes', json=cialo).status_code == 200
    kanaly = [z for z in wyslane_sygnaly if z != 'COMMIT']
    assert kanaly == ['station:packaging', 'station:gluing', 'station:cutting']
    assert 'COMMIT' in wyslane_sygnaly[:wyslane_sygnaly.index('station:packaging')]

    del wyslane_sygnaly[:]
    assert client.post(BASE + '/admin/apply-baselinker-changes', json=cialo).status_code == 200
    assert [z for z in wyslane_sygnaly if z != 'COMMIT'] == []

    del wyslane_sygnaly[:]
    assert client.post(BASE + '/admin/apply-baselinker-changes', json=cialo).get_json()['success'] is False
    assert [z for z in wyslane_sygnaly if z != 'COMMIT'] == []
