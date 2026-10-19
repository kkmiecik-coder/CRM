# -*- coding: utf-8 -*-
"""
Serwis hurtowej zmiany statusu (`modules/production/services/zmiana_statusu.py`).

Wydzielony z `products_api.bulk_action` na potrzeby tabletu kierownika hali. Kontrakt różni się od dawnej
funkcji w routerze dwoma rzeczami: serwis NIE commituje i NIE cofa transakcji (robi to wołający), a wynik niesie
dodatkowe klucze (`pozycje`, `nieznane`, `nowe_stanowisko`). Zachowanie całej ścieżki webowej pilnuje
`tests/test_produkty_masowa_zmiana_statusu.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.models import ProductionProduct
from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401
from tests.test_produkty_masowa_zmiana_statusu import _stan_logistyki, _zamowienie_logistyki


def _status(product_id):
    db.session.rollback()
    return db.session.get(ProductionProduct, product_id).current_status


def test_dozwolone_statusy_bez_logistycznych():
    from modules.production.services.zmiana_statusu import DOZWOLONE_STATUSY
    assert isinstance(DOZWOLONE_STATUSY, frozenset)
    assert 'zweryfikowane' not in DOZWOLONE_STATUSY and 'czeka_na_logistyke' not in DOZWOLONE_STATUSY
    assert {'zaladowane', 'dostarczone'}.isdisjoint(DOZWOLONE_STATUSY)
    assert {'spakowane', 'wstrzymane', 'anulowane'} <= DOZWOLONE_STATUSY


def test_serwis_nie_commituje(app, monkeypatch):
    from modules.production.services import zmiana_statusu
    pid, _ = produkt(app, status='czeka_na_formatowanie')
    with app.app_context():
        wywolania = []
        commit, rollback = db.session.commit, db.session.rollback
        monkeypatch.setattr(db.session, 'commit', lambda: wywolania.append('commit') or commit())
        monkeypatch.setattr(db.session, 'rollback', lambda: wywolania.append('rollback') or rollback())

        wynik = zmiana_statusu.zmien_status([pid], 'wstrzymane')

        assert wynik['success'] is True and wynik['processed_count'] == 1
        assert wywolania == []                      # ani commit, ani rollback: robi to wołający
        monkeypatch.undo()
        assert _status(pid) == 'czeka_na_formatowanie'   # po rollbacku wołającego zmiana znika


def test_wynik_niesie_klucze_dla_wolajacego(app):
    from modules.production.services import zmiana_statusu
    pid, _ = produkt(app, status='czeka_na_formatowanie')
    with app.app_context():
        wynik = zmiana_statusu.zmien_status([pid], 'czeka_na_krawedzie')

        assert [p.id for p in wynik['pozycje']] == [pid]
        assert wynik['pozycje'][0].current_status == 'czeka_na_krawedzie'
        assert wynik['nieznane'] == []
        assert wynik['nowe_stanowisko'] == 'edges'
        assert wynik['zdjete_stanowiska'] == []
        db.session.rollback()


def test_odmowa_wszystkich_success_false_bez_rollbacku(app, monkeypatch):
    from modules.production.services import zmiana_statusu
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(
        app, '25/00701', statusy=('zaladowane', 'zaladowane'), status_trasy='w_trasie', zaladowane=True)
    with app.app_context():
        wywolania = []
        commit, rollback = db.session.commit, db.session.rollback
        monkeypatch.setattr(db.session, 'commit', lambda: wywolania.append('commit') or commit())
        monkeypatch.setattr(db.session, 'rollback', lambda: wywolania.append('rollback') or rollback())

        wynik = zmiana_statusu.zmien_status(pozycje, 'czeka_na_pakowanie')

        assert wynik['success'] is False and wynik['processed_count'] == 0 and wynik['failed_count'] == 2
        assert wynik['error'] and wynik['error'] == u' '.join(wynik['errors'])
        assert wynik['nieznane'] == [] and wynik['zdjete_stanowiska'] == []
        assert wynik['nowe_stanowisko'] is None          # nic nie zapisano, żadne stanowisko nie dostało pracy
        assert wywolania == []                      # nawet przy odmowie wołający cofa transakcję sam
        db.session.rollback()
    assert _stan_logistyki(order_id)[0] == ['zaladowane', 'zaladowane']


def test_worker_id_w_logu_logistyki_po_regule_uniewaznienia(app):
    """Cofnięcie spakowanego do produkcji z `worker_id=7`: wpisy reguły (`paczki`) niosą pracownika, nie użytkownika."""
    from modules.production.logistics.models import LogisticsLog
    from modules.production.services import zmiana_statusu
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(
        app, '25/00702', statusy=('spakowane', 'spakowane'), zweryfikowane=False)
    with app.app_context():
        wynik = zmiana_statusu.zmien_status([pozycje[0]], 'czeka_na_pakowanie', worker_id=7,
                                            opis=u'zmiana statusu na tablecie kierownika')

        assert wynik['success'] is True
        wpisy = LogisticsLog.query.filter_by(order_id=order_id).order_by(LogisticsLog.id).all()
        assert [w.action for w in wpisy] == ['paczki']
        assert [(w.worker_id, w.user_id, w.note) for w in wpisy] == [
            (7, None, u'zmiana statusu na tablecie kierownika')]
        db.session.rollback()


def test_worker_id_w_logu_przy_cofnieciu_weryfikacji_hurtem(app):
    """Gałąź A1 (`_cofnij_weryfikacje_hurtem`): hurt na „spakowane” na zweryfikowanym zamówieniu też loguje pracownika."""
    from modules.production.logistics.models import LogisticsLog
    from modules.production.services import zmiana_statusu
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(app, '25/00703')
    with app.app_context():
        wynik = zmiana_statusu.zmien_status([pozycje[0]], 'spakowane', worker_id=7)

        assert wynik['success'] is True
        wpisy = LogisticsLog.query.filter_by(order_id=order_id).all()
        assert [(w.action, w.worker_id, w.user_id, w.note) for w in wpisy] == [
            ('weryfikacja_cofnieta', 7, None, u'zmiana statusu w panelu')]
        db.session.rollback()


def test_user_id_w_logu_logistyki_zostaje_dla_panelu(app):
    from modules.production.logistics.models import LogisticsLog
    from modules.production.services import zmiana_statusu
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(app, '25/00704')
    with app.app_context():
        zmiana_statusu.zmien_status([pozycje[0]], 'spakowane', user_id=3)

        wpis = LogisticsLog.query.filter_by(order_id=order_id).one()
        assert (wpis.user_id, wpis.worker_id) == (3, None)
        db.session.rollback()


def test_nieznane_ids(app):
    from modules.production.services import zmiana_statusu
    pid, _ = produkt(app, status='czeka_na_formatowanie')
    with app.app_context():
        wynik = zmiana_statusu.zmien_status([pid, 999999], 'wstrzymane')

        assert wynik['nieznane'] == [999999]
        assert [p.id for p in wynik['pozycje']] == [pid] and wynik['processed_count'] == 1
        db.session.rollback()


def test_brak_pozycji_zwraca_none(app):
    from modules.production.services import zmiana_statusu
    with app.app_context():
        assert zmiana_statusu.zmien_status([999999], 'wstrzymane') is None


def test_odpowiedz_webowa_bez_kluczy_serwisu(client, app):
    """Kształt odpowiedzi `bulk_action` bez zmian: klucze tylko-dla-serwisu (ORM nie serializuje się) są obcinane."""
    pid, _ = produkt(app, status='czeka_na_formatowanie')
    r = client.post(BASE + '/products/bulk-action', json={
        'action': 'update_status', 'product_ids': [pid], 'parameters': {'new_status': 'czeka_na_krawedzie'}})
    assert r.status_code == 200, r.get_data()[:500]
    assert sorted(r.get_json()) == ['action', 'errors', 'failed_count', 'processed_count', 'success',
                                    'zdjete_stanowiska']
    with app.app_context():
        assert _status(pid) == 'czeka_na_krawedzie'      # commit robi bulk_action


def test_odmowa_webowa_409_bez_kluczy_serwisu_i_bez_zapisu(client, app):
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(
        app, '25/00705', statusy=('zaladowane', 'zaladowane'), status_trasy='zaladowana', zaladowane=True)
    r = client.post(BASE + '/products/bulk-action', json={
        'action': 'update_status', 'product_ids': pozycje, 'parameters': {'new_status': 'czeka_na_pakowanie'}})
    assert r.status_code == 409, r.get_data()[:500]
    assert sorted(r.get_json()) == ['action', 'error', 'errors', 'failed_count', 'processed_count', 'success']
    assert _stan_logistyki(order_id)[0] == ['zaladowane', 'zaladowane']
