"""Testy cache cenników w pamięci procesu (load_pricing_data/invalidate_pricing_cache).

Bez realnej DB — monkeypatch na _build_pricing_data (liczymy wywołania),
żeby nie zależeć od danych w bazie ani od kontekstu aplikacji Flask.
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

    # W oknie TTL (120s) - wciąż cache
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
