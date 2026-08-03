"""Testy audytu zmian statusu produktu (product_events)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.models import ProductionProductEvent


def test_model_ma_wymagane_kolumny():
    cols = set(ProductionProductEvent.__table__.columns.keys())
    assert cols == {
        'id', 'production_item_id', 'event_type', 'old_value', 'new_value',
        'actor_type', 'user_id', 'device_id', 'source', 'endpoint',
        'ip_address', 'note', 'created_at',
    }


def test_model_wskazuje_na_wlasciwa_tabele():
    assert ProductionProductEvent.__tablename__ == 'prod_product_events'


from types import SimpleNamespace

from modules.production.services.product_events import build_actor


def test_aktor_tablet_ma_device_id_i_source_mobile():
    device = SimpleNamespace(device_id='bd10cec3-140d')
    a = build_actor(device=device, endpoint='mobile_api.order_complete', ip_address='10.0.0.5')
    assert a.actor_type == 'device'
    assert a.device_id == 'bd10cec3-140d'
    assert a.source == 'mobile'
    assert a.user_id is None
    assert a.endpoint == 'mobile_api.order_complete'


def test_aktor_zalogowany_uzytkownik_ma_user_id_i_source_web():
    user = SimpleNamespace(id=7, is_authenticated=True)
    a = build_actor(user=user, endpoint='production_api.bulk_action', ip_address='1.2.3.4')
    assert a.actor_type == 'user'
    assert a.user_id == 7
    assert a.source == 'web'
    assert a.device_id is None


def test_aktor_bez_kontekstu_to_system():
    a = build_actor()
    assert a.actor_type == 'system'
    assert a.source == 'system'
    assert a.user_id is None and a.device_id is None


def test_tablet_ma_pierwszenstwo_przed_userem():
    # Żądanie mobilne z przypadkowo aktywną sesją web — liczy się urządzenie
    device = SimpleNamespace(device_id='dev-1')
    user = SimpleNamespace(id=7, is_authenticated=True)
    a = build_actor(user=user, device=device)
    assert a.actor_type == 'device'


def test_niezalogowany_user_nie_jest_aktorem():
    user = SimpleNamespace(id=None, is_authenticated=False)
    a = build_actor(user=user)
    assert a.actor_type == 'system'


def test_brak_urzadzenia_i_usera_ale_w_kontekscie_zadania_to_source_web():
    # Poprawka 2: panel stanowiskowy (/production/stations/complete-order,
    # /production/api/complete-task) jest chroniony walidacją IP, a nie
    # logowaniem — nie ma ani g.device, ani zalogowanego usera, ale JEST
    # żądanie HTTP. To ma dać source='web', nie 'system', żeby dało się
    # odróżnić człowieka przy stanowisku od automatu.
    a = build_actor(in_request=True)
    assert a.actor_type == 'system'
    assert a.source == 'web'


def test_brak_kontekstu_zadania_to_dalej_source_system():
    # Scheduler/CLI/synchronizacja BaseLinkera — brak żądania HTTP w ogóle.
    a = build_actor()
    assert a.actor_type == 'system'
    assert a.source == 'system'


from datetime import datetime

from modules.production.services.product_events import build_event_rows

_NOW = datetime(2026, 7, 31, 10, 38, 44)
_ACTOR = SimpleNamespace(
    actor_type='device', user_id=None, device_id='dev-1',
    source='mobile', endpoint='mobile_api.order_complete', ip_address='10.0.0.5',
)


def test_zmiana_statusu_daje_wiersz_status_change():
    rows = build_event_rows(55, [('current_status', 'czeka_na_skladanie', 'czeka_na_sklejanie')], _ACTOR, _NOW)
    assert len(rows) == 1
    r = rows[0]
    assert r['production_item_id'] == 55
    assert r['event_type'] == 'status_change'
    assert r['old_value'] == 'czeka_na_skladanie'
    assert r['new_value'] == 'czeka_na_sklejanie'
    assert r['actor_type'] == 'device'
    assert r['device_id'] == 'dev-1'
    assert r['endpoint'] == 'mobile_api.order_complete'
    assert r['created_at'] == _NOW


def test_brak_zmiany_nie_daje_wiersza():
    rows = build_event_rows(55, [('current_status', 'czeka_na_skladanie', 'czeka_na_skladanie')], _ACTOR, _NOW)
    assert rows == []


def test_niesledzone_pole_jest_ignorowane():
    rows = build_event_rows(55, [('production_notes', 'a', 'b')], _ACTOR, _NOW)
    assert rows == []


def test_priorytet_jest_rzutowany_na_tekst():
    rows = build_event_rows(55, [('priority_rank', 120, 1)], _ACTOR, _NOW)
    assert rows[0]['event_type'] == 'priority_change'
    assert rows[0]['old_value'] == '120'
    assert rows[0]['new_value'] == '1'


def test_wartosc_none_zostaje_none_a_nie_tekstem():
    rows = build_event_rows(55, [('priority_rank', None, 5)], _ACTOR, _NOW)
    assert rows[0]['old_value'] is None
    assert rows[0]['new_value'] == '5'


def test_kilka_zmian_naraz_daje_kilka_wierszy():
    rows = build_event_rows(55, [
        ('current_status', 'a', 'b'),
        ('priority_rank', 10, 20),
    ], _ACTOR, _NOW)
    assert [r['event_type'] for r in rows] == ['status_change', 'priority_change']


from modules.production.services.product_events import build_event_rows_for_flush

_USER_ACTOR = SimpleNamespace(
    actor_type='user', user_id=7, device_id=None,
    source='web', endpoint='production_api.reorder', ip_address='1.2.3.4',
)
_SYSTEM_ACTOR = SimpleNamespace(
    actor_type='system', user_id=None, device_id=None,
    source='sync', endpoint='sync_service.run', ip_address=None,
)


def test_pojedyncza_reczna_zmiana_priorytetu_zostaje_zapisana():
    changes_by_product = [(55, [('priority_rank', 10, 9)])]
    rows = build_event_rows_for_flush(changes_by_product, _USER_ACTOR, _NOW)
    assert len(rows) == 1
    assert rows[0]['event_type'] == 'priority_change'


def test_masowa_renumeracja_ponad_progiem_pomija_priority_change():
    # 6 produktów ze zmianą priorytetu w jednym flushu (próg = 5) — to
    # assign_sequential_ranks renumerujący całą kolejkę, nie decyzja o
    # pojedynczym produkcie.
    changes_by_product = [
        (i, [('priority_rank', i, i - 1)]) for i in range(1, 7)
    ]
    rows = build_event_rows_for_flush(changes_by_product, _USER_ACTOR, _NOW)
    assert rows == []


def test_masowa_renumeracja_dokladnie_na_progu_jest_jeszcze_zapisywana():
    # Dokładnie 5 zmian (próg to "przekracza 5", więc 5 samo w sobie
    # jeszcze się mieści i zostaje zapisane).
    changes_by_product = [
        (i, [('priority_rank', i, i - 1)]) for i in range(1, 6)
    ]
    rows = build_event_rows_for_flush(changes_by_product, _USER_ACTOR, _NOW)
    assert len(rows) == 5
    assert all(r['event_type'] == 'priority_change' for r in rows)


def test_status_change_w_tym_samym_flushu_co_masowa_renumeracja_zostaje():
    # Zmiany statusu NIE mogą zostać zatopione przez filtr priorytetów —
    # dotyczy on wyłącznie priority_change.
    changes_by_product = [(i, [('priority_rank', i, i - 1)]) for i in range(1, 7)]
    changes_by_product.append((99, [('current_status', 'a', 'b')]))
    rows = build_event_rows_for_flush(changes_by_product, _USER_ACTOR, _NOW)
    assert len(rows) == 1
    assert rows[0]['event_type'] == 'status_change'
    assert rows[0]['production_item_id'] == 99


def test_priority_change_automatu_jest_zawsze_pomijana_nawet_pojedyncza():
    # Automat (np. przeliczenie w tle) nigdy nie podejmuje pojedynczej,
    # świadomej decyzji o priorytecie — filtr obowiązuje niezależnie od progu.
    changes_by_product = [(55, [('priority_rank', 10, 9)])]
    rows = build_event_rows_for_flush(changes_by_product, _SYSTEM_ACTOR, _NOW)
    assert rows == []


import modules.production.services.product_events as product_events_module
from modules.production.services.product_events import _audit_table_available


def _reset_audit_table_cache():
    """Zeruje pamiętany wynik sprawdzenia tabeli, żeby testy się nie widziały."""
    product_events_module._TABLE_AVAILABLE = False
    product_events_module._LAST_CHECK_MONOTONIC = None


def test_audyt_dostepny_gdy_tabela_istnieje():
    _reset_audit_table_cache()
    assert _audit_table_available(check_fn=lambda: True) is True
    _reset_audit_table_cache()


def test_audyt_niedostepny_gdy_tabeli_brak():
    _reset_audit_table_cache()
    assert _audit_table_available(check_fn=lambda: False) is False
    _reset_audit_table_cache()


def test_audyt_niedostepny_gdy_sprawdzenie_rzuca_wyjatek():
    # Samo sprawdzenie też nie może niczego wywrócić — wyjątek z check_fn
    # ma skutkować "audyt niedostępny", a nie propagacją błędu.
    def _boom():
        raise RuntimeError("baza chwilowo niedostępna")

    _reset_audit_table_cache()
    assert _audit_table_available(check_fn=_boom) is False
    _reset_audit_table_cache()


def test_wynik_sprawdzenia_tabeli_jest_pamietany_bez_ponownego_odpytania():
    calls = {'count': 0}

    def _check_fn():
        calls['count'] += 1
        return True

    _reset_audit_table_cache()
    assert _audit_table_available(check_fn=_check_fn) is True
    # Drugie i trzecie wywołanie nie powinny już odpytywać check_fn —
    # wynik ma być zapamiętany (to jest gorący kod, wykonywany przy każdym
    # flushu w całej aplikacji).
    assert _audit_table_available(check_fn=_check_fn) is True
    assert _audit_table_available(check_fn=_check_fn) is True
    assert calls['count'] == 1
    _reset_audit_table_cache()


def test_wynik_negatywny_jest_ponawiany_po_300_sekundach():
    # Poprawka 1 (regres krytyczny): wynik NEGATYWNY nie może zostać
    # zapamiętany na zawsze, bo administrator mógł wykonać migrację PO
    # starcie procesu — audyt milczałby wtedy do restartu aplikacji.
    calls = {'count': 0}
    fake_now = {'t': 1000.0}

    def _check_fn():
        calls['count'] += 1
        return False

    real_monotonic = product_events_module.time.monotonic
    product_events_module.time.monotonic = lambda: fake_now['t']
    try:
        _reset_audit_table_cache()
        assert _audit_table_available(check_fn=_check_fn) is False
        assert calls['count'] == 1

        # W oknie 300s: żadnego kolejnego odpytania bazy.
        fake_now['t'] += 100
        assert _audit_table_available(check_fn=_check_fn) is False
        assert calls['count'] == 1

        # Po upływie 300s: wolno ponowić próbę.
        fake_now['t'] += 300
        assert _audit_table_available(check_fn=_check_fn) is False
        assert calls['count'] == 2
    finally:
        product_events_module.time.monotonic = real_monotonic
        _reset_audit_table_cache()


def test_wynik_pozytywny_zostaje_zapamietany_na_zawsze_mimo_uplywu_czasu():
    calls = {'count': 0}
    fake_now = {'t': 1000.0}

    def _check_fn():
        calls['count'] += 1
        return True

    real_monotonic = product_events_module.time.monotonic
    product_events_module.time.monotonic = lambda: fake_now['t']
    try:
        _reset_audit_table_cache()
        assert _audit_table_available(check_fn=_check_fn) is True
        assert calls['count'] == 1

        # Nawet po długim czasie wynik pozytywny nie jest odświeżany.
        fake_now['t'] += 10_000
        assert _audit_table_available(check_fn=_check_fn) is True
        assert calls['count'] == 1
    finally:
        product_events_module.time.monotonic = real_monotonic
        _reset_audit_table_cache()


def test_negatywny_wynik_loguje_blad_tylko_raz_na_probe_odswiezenia():
    # Nie loguj przy każdym ponownym wywołaniu w oknie 300s — tylko przy
    # pierwszym sprawdzeniu i potem najwyżej raz na próbę odświeżenia.
    fake_now = {'t': 1000.0}
    log_calls = {'count': 0}

    def _check_fn():
        return False

    real_monotonic = product_events_module.time.monotonic
    real_error = product_events_module.logger.error
    product_events_module.time.monotonic = lambda: fake_now['t']
    product_events_module.logger.error = lambda *a, **k: log_calls.__setitem__(
        'count', log_calls['count'] + 1)
    try:
        _reset_audit_table_cache()
        _audit_table_available(check_fn=_check_fn)
        _audit_table_available(check_fn=_check_fn)
        _audit_table_available(check_fn=_check_fn)
        assert log_calls['count'] == 1

        fake_now['t'] += 300
        _audit_table_available(check_fn=_check_fn)
        assert log_calls['count'] == 2
    finally:
        product_events_module.time.monotonic = real_monotonic
        product_events_module.logger.error = real_error
        _reset_audit_table_cache()
