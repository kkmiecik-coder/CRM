"""Testy cache cenników w pamięci procesu (load_pricing_data/invalidate_pricing_cache).

Bez realnej DB — monkeypatch na _build_pricing_data (liczymy wywołania),
żeby nie zależeć od danych w bazie ani od kontekstu aplikacji Flask.
Odcisk cennika (_pricing_fingerprint) też jest podmieniany — testy sprawdzają
samą mechanikę rewalidacji, nie SQL-a.
"""
import modules.calculator.services.pricing_service as pricing_service
from modules.calculator.services.pricing_service import (
    load_pricing_data, invalidate_pricing_cache, PricingData,
)


def _reset_cache():
    """Cache modułowy jest globalny — czyścimy przed/po każdym teście, żeby
    testy się nie zatruwały nawzajem (kolejność uruchomienia pytest nie jest
    gwarantowana)."""
    invalidate_pricing_cache()


def test_load_pricing_data_dwa_razy_pod_rzad_zwraca_ten_sam_obiekt(monkeypatch):
    """W oknie TTL druga wywołanie NIE odpytuje bazy — dostaje ten sam obiekt (is)."""
    _reset_cache()
    calls = {'n': 0}

    def fake_build():
        calls['n'] += 1
        return PricingData()

    monkeypatch.setattr(pricing_service, '_build_pricing_data', fake_build)

    first = load_pricing_data()
    second = load_pricing_data()

    assert first is second
    assert calls['n'] == 1
    _reset_cache()


def test_invalidate_pricing_cache_wymusza_nowy_obiekt(monkeypatch):
    """Po invalidate_pricing_cache() kolejne wywołanie buduje NOWY obiekt (is not)."""
    _reset_cache()
    calls = {'n': 0}

    def fake_build():
        calls['n'] += 1
        return PricingData()

    monkeypatch.setattr(pricing_service, '_build_pricing_data', fake_build)

    first = load_pricing_data()
    invalidate_pricing_cache()
    second = load_pricing_data()

    assert first is not second
    assert calls['n'] == 2
    _reset_cache()


def test_use_cache_false_zawsze_buduje_od_nowa(monkeypatch):
    """use_cache=False pomija cache całkowicie (np. golden check / porównania z DB)."""
    _reset_cache()
    calls = {'n': 0}

    def fake_build():
        calls['n'] += 1
        return PricingData()

    monkeypatch.setattr(pricing_service, '_build_pricing_data', fake_build)

    first = load_pricing_data(use_cache=False)
    second = load_pricing_data(use_cache=False)

    assert first is not second
    assert calls['n'] == 2
    _reset_cache()


def test_cache_wygasa_po_ttl(monkeypatch):
    """Symulujemy upływ czasu > TTL — cache powinien zostać zbudowany od nowa."""
    _reset_cache()
    calls = {'n': 0}

    def fake_build():
        calls['n'] += 1
        return PricingData()

    monkeypatch.setattr(pricing_service, '_build_pricing_data', fake_build)

    fake_time = {'t': 1000.0}
    monkeypatch.setattr(pricing_service.time, 'time', lambda: fake_time['t'])

    first = load_pricing_data()
    assert calls['n'] == 1

    # W oknie TTL (PRICING_CACHE_TTL=3600s) - wciąż cache
    fake_time['t'] += 10
    second = load_pricing_data()
    assert second is first
    assert calls['n'] == 1

    # Po TTL - nowy obiekt
    fake_time['t'] += pricing_service.PRICING_CACHE_TTL + 1
    third = load_pricing_data()
    assert third is not first
    assert calls['n'] == 2
    _reset_cache()


# ---------------------------------------------------------------------------
# Rewalidacja odciskiem — zmiana cennika POZA aplikacją (phpMyAdmin) ma wejść
# w kilkanaście sekund, w KAŻDYM workerze gunicorna, bez restartu.
# ---------------------------------------------------------------------------

def _setup_cache_test(monkeypatch, fingerprint_value):
    """Podmienia budowanie cennika, odcisk i zegar. Zwraca liczniki + sterowanie."""
    _reset_cache()
    state = {'builds': 0, 'fingerprint_calls': 0,
             'fingerprint': fingerprint_value, 't': 1000.0}

    def fake_build():
        state['builds'] += 1
        return PricingData()

    def fake_fingerprint():
        state['fingerprint_calls'] += 1
        return state['fingerprint']

    monkeypatch.setattr(pricing_service, '_build_pricing_data', fake_build)
    monkeypatch.setattr(pricing_service, '_pricing_fingerprint', fake_fingerprint)
    monkeypatch.setattr(pricing_service.time, 'time', lambda: state['t'])
    return state


def test_zmiana_odcisku_przebudowuje_cache_bez_restartu(monkeypatch):
    """Ktoś zmienił ceny w phpMyAdmin — po oknie rewalidacji cache buduje się od nowa."""
    state = _setup_cache_test(monkeypatch, 'ODCISK-A')

    first = load_pricing_data()
    assert state['builds'] == 1

    # Ten sam odcisk po oknie rewalidacji — bez przebudowy
    state['t'] += pricing_service.PRICING_REVALIDATE_SECONDS + 1
    assert load_pricing_data() is first
    assert state['builds'] == 1

    # Zmiana w bazie => inny odcisk => nowy obiekt
    state['fingerprint'] = 'ODCISK-B'
    state['t'] += pricing_service.PRICING_REVALIDATE_SECONDS + 1
    second = load_pricing_data()
    assert second is not first
    assert state['builds'] == 2
    _reset_cache()


def test_odcisk_nie_jest_sprawdzany_czesciej_niz_okno(monkeypatch):
    """W oknie rewalidacji nie ma ŻADNEGO zapytania o odcisk — cache oddaje dane od ręki."""
    state = _setup_cache_test(monkeypatch, 'ODCISK-A')

    load_pricing_data()
    calls_po_budowie = state['fingerprint_calls']

    state['t'] += 1
    load_pricing_data()
    load_pricing_data()

    assert state['fingerprint_calls'] == calls_po_budowie
    assert state['builds'] == 1
    _reset_cache()


def test_brak_odcisku_zachowuje_stare_zachowanie_ttl(monkeypatch):
    """Gdy odcisku nie da się policzyć (brak kontekstu/DB) — cache działa jak dawniej, na TTL."""
    state = _setup_cache_test(monkeypatch, None)

    first = load_pricing_data()

    state['t'] += pricing_service.PRICING_REVALIDATE_SECONDS + 1
    assert load_pricing_data() is first
    assert state['builds'] == 1

    state['t'] += pricing_service.PRICING_CACHE_TTL + 1
    assert load_pricing_data() is not first
    assert state['builds'] == 2
    _reset_cache()


def test_odcisk_zapamietany_przy_budowie_pochodzi_sprzed_odczytu_danych(monkeypatch):
    """Odcisk liczymy PRZED budową — zapis w trakcie budowy zostanie wykryty przy
    następnej rewalidacji (bezpieczny kierunek błędu: nadmiarowa przebudowa)."""
    state = _setup_cache_test(monkeypatch, 'ODCISK-A')

    def build_zmieniajacy_baze():
        state['builds'] += 1
        state['fingerprint'] = 'ODCISK-B'   # ktoś zapisał cennik w trakcie budowy
        return PricingData()

    monkeypatch.setattr(pricing_service, '_build_pricing_data', build_zmieniajacy_baze)

    first = load_pricing_data()
    assert state['builds'] == 1

    state['t'] += pricing_service.PRICING_REVALIDATE_SECONDS + 1
    assert load_pricing_data() is not first
    assert state['builds'] == 2
    _reset_cache()
